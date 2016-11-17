from setuptools import setup
from setuptools.command.develop import develop as _develop
from setuptools.command.install import install as _install
from notebook.nbextensions import install_nbextension
from notebook.services.config import ConfigManager
import os

extension_dir = os.path.join(os.path.dirname(__file__), "juno_magic", "static")

class develop(_develop):
    def run(self):
        _develop.run(self)
        install_nbextension(extension_dir, symlink=True,
                            overwrite=True, user=True, destination="juno_magic")
        cm = ConfigManager()
        cm.update('notebook', {"load_extensions": {"juno_magic/index": True } })

class install(_install):
    def run(self):
        _install.run(self)
        cm = ConfigManager()
        cm.update('notebook', {"load_extensions": {"juno_magic/index": True } })

setup(name='juno-magic',
      cmdclass={'develop': develop, 'install': install},
      version='0.1.12',
      description='IPython magics and utilities to work with bridged kernels',
      url='https://github.com/timbr-io/juno-magic',
      author='Pramukta Kumar',
      author_email='pramukta.kumar@timbr.io',
      license='MIT',
      packages=['juno_magic', 'juno_magic.extensions'],
      zip_safe=False,
      data_files=[
        ('share/jupyter/nbextensions/juno_magic', [
            'juno_magic/static/index.js'
        ]),
      ],
      entry_points={
          "console_scripts": [
              "wampify = juno_magic.bridge:main"
          ]
      },
      install_requires=[
          "ipython",
          "autobahn",
          "twisted",
          "txzmq",
          "sh",
          "pyopenssl",
          "service_identity",
          "requests",
          "zope.interface"
        ]
      )
