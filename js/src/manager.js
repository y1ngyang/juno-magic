var Component = require('./component');

module.exports = function( target, kernel ) {

    this.components = {};

    kernel.comm_manager.register_target( target, function( comm, msg ) {
      if ( msg['msg_type'] === 'comm_open' ) {
        //console.log('open comm', msg)
        this.components[ comm.comm_id ] = new Component( comm, msg );
      }
    });

    return this;
};