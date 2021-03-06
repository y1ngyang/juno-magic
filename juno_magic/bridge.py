from twisted.internet.error import ReactorAlreadyInstalledError
from zmq.eventloop import ioloop
ioloop.install()
from tornado.ioloop import IOLoop
import tornado.platform.twisted
try:
    tornado.platform.twisted.install()
except ReactorAlreadyInstalledError:
    pass

#from jupyter_client.blocking.client import BlockingKernelClient
from .client import BlockingKernelClient
from ipykernel.jsonutil import json_clean

from twisted.python import log
from twisted.internet import threads
from twisted.internet.defer import inlineCallbacks, returnValue, CancelledError, DeferredLock
from twisted.internet.task import LoopingCall
from twisted.internet.error import ConnectionRefusedError
from autobahn.twisted.util import sleep
from autobahn.twisted.wamp import ApplicationSession, ApplicationRunner, Service
from autobahn import wamp
from autobahn.wamp.exception import ApplicationError

from txzmq import ZmqEndpoint, ZmqFactory, ZmqSubConnection

import json
import sys
import os
import argparse
from pprint import pformat
try:
    from queue import Empty  # Python 3
except ImportError:
    from Queue import Empty  # Python 2

if sys.version.startswith("3"):
    unicode = str


_zmq_factory = ZmqFactory()

def cleanup(proto):
    if hasattr(proto, '_session') and proto._session is not None:
        if proto._session.is_attached():
            return proto._session.leave()
        elif proto._session.is_connected():
            return proto._session.disconnect()

class ZmqProxyConnection(ZmqSubConnection):
    def __init__(self, endpoint, wamp_session, prefix):
        self._endpoint = endpoint
        self._wamp = wamp_session
        self._prefix = prefix
        ZmqSubConnection.__init__(self, _zmq_factory, ZmqEndpoint('connect', endpoint.encode("utf-8")))
        self.subscribe(b"")

    def gotMessage(self, message, header=""):
        # log.msg("[MachineConnection] {} {}".format(header, message))
        self._wamp.publish(self._prefix, [str(header), json.loads(message.decode("utf-8"))])


def build_bridge_class(client):
    _key = client.session.key.decode("utf-8")
    class JupyterClientWampBridge(ApplicationSession):
        iopub_deferred = None
        prefix_list = set()
        machine_connection = None
        _lock = DeferredLock()
        _has_been_pinged = False
        _has_timedout = False

        @wamp.register(u"io.timbr.kernel.{}.execute".format(_key))
        @inlineCallbacks
        def execute(self, *args, **kwargs):
            result = yield client.execute(*args, **kwargs)
            returnValue(result)

        @wamp.register(u"io.timbr.kernel.{}.execute_interactive".format(_key))
        @inlineCallbacks
        def execute_interactive(self, *args, **kwargs):
            result = yield self._lock.run(threads.deferToThread, client.execute_interactive, *args, **kwargs)
            returnValue(json_clean(result))

        @wamp.register(u"io.timbr.kernel.{}.complete_interactive".format(_key))
        @inlineCallbacks
        def complete_interactive(self, *args, **kwargs):
            result = yield self._lock.run(threads.deferToThread, client.interactive, client.complete, *args, **kwargs)
            returnValue(json_clean(result))

        @wamp.register(u"io.timbr.kernel.{}.complete".format(_key))
        @inlineCallbacks
        def complete(self, *args, **kwargs):
            result = yield client.complete(*args, **kwargs)
            returnValue(result)

        @wamp.register(u"io.timbr.kernel.{}.inspect".format(_key))
        @inlineCallbacks
        def inspect(self, *args, **kwargs):
            result = yield client.inspect(*args, **kwargs)
            returnValue(result)

        @wamp.register(u"io.timbr.kernel.{}.history".format(_key))
        @inlineCallbacks
        def history(self, *args, **kwargs):
            result = yield client.history(*args, **kwargs)
            returnValue(result)

        @wamp.register(u"io.timbr.kernel.{}.is_complete".format(_key))
        @inlineCallbacks
        def is_complete(self, *args, **kwargs):
            result = yield client.is_complete(*args, **kwargs)
            returnValue(result)

        @wamp.register(u"io.timbr.kernel.{}.shutdown".format(_key))
        @inlineCallbacks
        def shutdown(self, *args, **kwargs):
            result = yield client.shutdown(*args, **kwargs)
            returnValue(result)

        @wamp.register(u"io.timbr.kernel.{}.list".format(_key))
        def list(self):
            return list(self.prefix_list)

        # This is relies heavily on shell_channel property on the client
        # need to pay attention to Jupyter.client if/when this changes...
        @wamp.register(u"io.timbr.kernel.{}.comm_msg".format(_key))
        def comm_msg(self, *args, **kwargs):
            msg = kwargs.get('msg', {})
            log.msg("[comm_msg] {}".format(pformat(json_clean(msg))))
            return client.shell_channel.send(msg)

        @inlineCallbacks
        def proxy_iopub_channel(self):
            while True:
                try:
                    msg = client.get_iopub_msg(block=False)
                    if(not msg["content"].get("metadata", {}).get("echo", False)):
                        log.msg("[iopub] {}".format(pformat(json_clean(msg))))
                        yield self.publish(u"io.timbr.kernel.{}.iopub".format(_key), json_clean(msg))
                except ValueError as ve:
                    # This happens when an "invalid signature" is encountered which for us probably
                    # means that the message did not originate from this kernel
                    log.msg("ValueError")
                except Empty:
                    yield sleep(0.1)

        def proxy_machine_channel(self):
            """
            If there is a timbr-machine zeromq pub channel present for this kernel_id it will be
            proxied over the WAMP connection at io.timbr.kernel.<kernel_id>.machine
            """
            ipc_endpoint = "ipc:///tmp/timbr-machine/{}".format(_key) # NOTE: Breaks Windows compatibility
            prefix = "io.timbr.kernel.{}.machine".format(_key)
            self.machine_connection = ZmqProxyConnection(ipc_endpoint, self, prefix)

        @wamp.register(u"io.timbr.kernel.{}.ping".format(_key))
        def ping(self):
            self._has_been_pinged = True
            response =  client.is_alive()
#            log.msg("PINGED from EXTERNAL APPLICATION: returned {}".format(response))
            return response

        @wamp.register(u"io.timbr.kernel.{}.nw_ping".format(_key))
        def nw_ping(self):
            return client.is_alive()

        @inlineCallbacks
        def is_active(self, prefix):
            try:
                response = yield self.call(u"{}.nw_ping".format(prefix))
            except ApplicationError:
                response = False
            finally:
#                log.msg("PINGED from WAMPIFY NETWORK: returned {}".format(response))
                returnValue(response)

        def on_discovery(self, prefix):
            self.prefix_list.add(prefix)

        @inlineCallbacks
        def update_discovery(self):
            my_prefix = u"io.timbr.kernel.{}".format(_key)
            yield self.publish(u"io.timbr.kernel.discovery", my_prefix)
            prefix_list = list(self.prefix_list)
            active_prefix_list = []
            for prefix in prefix_list:
                is_active = yield self.is_active(prefix)
                if is_active is True:
                    active_prefix_list.append(prefix)
            self.prefix_list = set(active_prefix_list)
            try:
                yield self.register(self.list, u"io.timbr.kernel.list")
            except ApplicationError:
                pass
            returnValue(self.prefix_list)

        @inlineCallbacks
        def onJoin(self, details):
            log.msg("[onJoin] Registering WAMP methods...")
            yield self.register(self)
            log.msg("[onJoin] ...done.")
            log.msg("[onJoin] Updating kernel discovery mechanism")
            yield self.subscribe(self.on_discovery, u"io.timbr.kernel.discovery")
            self.discovery_task = LoopingCall(self.update_discovery)
            self.discovery_task.start(3) # loop every 3 seconds
            log.msg("[onJoin] Establishing Pub/Sub Channels...")
            try:
                self.iopub_deferred.cancel()
            except (CancelledError, AttributeError):
                pass
            finally:
                self.iopub_deferred = self.proxy_iopub_channel()
            try:
                self.machine_connection.shutdown()
            except AttributeError:
                pass
            #finally:
                #self.proxy_machine_channel()

            log.msg("[onJoin] ...done.")
            log.msg(client.hb_channel._running)

        @inlineCallbacks
        def onLeave(self, details):
            try:
                yield self.machine_connection.shutdown()
            except AttributeError:
                pass
            yield self.discovery_task.stop()
            super(self.__class__, self).onLeave(details)

        def onDisconnect(self):
            log.msg("[onDisconnect] ...")
            log.msg("Attempting to reconnect ...")

    return JupyterClientWampBridge



def main():
    global _bridge_runner

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable debug output.")
    # NOTE: all of these are placeholders
    parser.add_argument("--wamp-realm", default=u"jupyter", help='Router realm')
    parser.add_argument("--wamp-url", default=u"ws://127.0.0.1:8123", help="WAMP Websocket URL")
    parser.add_argument("--token", type=unicode, help="OAuth token to connect to router")
    parser.add_argument("--shutdown-interval", type=int, default=0, help="When set to positive non-zero value, shutdown remote processes after shutdown_interval number of seconds of no pings")
    parser.add_argument("file", help="Connection file")
    args = parser.parse_args()

    if args.debug:
        try:
            log.startLogging(open('/home/gremlin/wamp.log', 'w'), setStdout=False)
        except IOError:
            pass

    with open(args.file) as f:
        config = json.load(f)

    client = BlockingKernelClient(connection_file=args.file)
    client.load_connection_file()
    client.start_channels()

    _bridge_runner = ApplicationRunner(url=unicode(args.wamp_url), realm=unicode(args.wamp_realm),
                                headers={"Authorization": "Bearer {}".format(args.token),
                                         "X-Kernel-ID": client.session.key})

    log.msg("Connecting to router: %s" % args.wamp_url)
    log.msg("  Project Realm: %s" % (args.wamp_realm))

    def heartbeat(proto):
        if hasattr(proto, '_session') and proto._session is not None:
            if not proto._session._has_been_pinged:
                proto._session._has_timedout = True
            else:
                proto._session._has_been_pinged = False

    @inlineCallbacks
    def reconnector(shutdown_interval):
        shutdown_on_timeout = False
        if shutdown_interval > 0:
            shutdown_on_timeout = True
        while True:
            try:
                hb = None
                log.msg("Attempting to connect...")
                wampconnection = yield _bridge_runner.run(build_bridge_class(client), start_reactor=False)
                if shutdown_on_timeout:
                    hb = LoopingCall(heartbeat, (wampconnection))
                    hb.start(shutdown_interval, now=False)
                log.msg(wampconnection)
                yield sleep(10.0) # Give the connection time to set _session
                while wampconnection.isOpen():
                    if shutdown_on_timeout:
                        if wampconnection._session._has_timedout:
                            hb.stop()
                            res = yield cleanup(wampconnection)
                            returnValue(res)
                    yield sleep(5.0)
            except ConnectionRefusedError as ce:
                if hb is not None and hb.running:
                    hb.stop()
                log.msg("ConnectionRefusedError: Trying to reconnect... ")
                yield sleep(1.0)

    def shutdown(result):
        log.msg("Comitting suicide")
        IOLoop.current().stop()
        import subprocess
        proc = subprocess.Popen(["python", "-m", "circus.circusctl", "quit"],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

    shutdown_interval = args.shutdown_interval
    try:
        shutdown_interval = int(os.environ.get('SHUTDOWN_INTERVAL'))
    except TypeError:
        pass

    d = reconnector(shutdown_interval)
    d.addCallback(shutdown)
    IOLoop.current().start()

if __name__ == "__main__":
    main()
