define(function() { return /******/ (function(modules) { // webpackBootstrap
/******/ 	// The module cache
/******/ 	var installedModules = {};

/******/ 	// The require function
/******/ 	function __webpack_require__(moduleId) {

/******/ 		// Check if module is in cache
/******/ 		if(installedModules[moduleId])
/******/ 			return installedModules[moduleId].exports;

/******/ 		// Create a new module (and put it into the cache)
/******/ 		var module = installedModules[moduleId] = {
/******/ 			exports: {},
/******/ 			id: moduleId,
/******/ 			loaded: false
/******/ 		};

/******/ 		// Execute the module function
/******/ 		modules[moduleId].call(module.exports, module, module.exports, __webpack_require__);

/******/ 		// Flag the module as loaded
/******/ 		module.loaded = true;

/******/ 		// Return the exports of the module
/******/ 		return module.exports;
/******/ 	}


/******/ 	// expose the modules object (__webpack_modules__)
/******/ 	__webpack_require__.m = modules;

/******/ 	// expose the module cache
/******/ 	__webpack_require__.c = installedModules;

/******/ 	// __webpack_public_path__
/******/ 	__webpack_require__.p = "";

/******/ 	// Load entry module and return exports
/******/ 	return __webpack_require__(0);
/******/ })
/************************************************************************/
/******/ ([
/* 0 */
/***/ function(module, exports, __webpack_require__) {

	// Configure requirejs
	if (window.require) {
	    window.require.config({
	        map: {
	            "*" : {
	                "react": "https://fb.me/react-15.2.1.min.js",
	                "react-dom": "https://fb.me/react-dom-15.2.1.min.js",
	                "components": "/nbextensions/juno_magic/components.js"
	            }
	        }
	    });
	}

	var mngr = __webpack_require__(1);
	var Component = __webpack_require__(2);

	var handle_kernel = function(Jupyter, kernel) {
	    if ( kernel.comm_manager ) {
	      manager = mngr( 'juno', kernel );
	      kernel.component_manager = manager;

	      kernel.comm_manager.register_target( 'juno.status', function( comm, msg ) {
	        console.log( comm, msg['content']['data'] )
	        Juno.statusComp = new Component( comm, msg['content']['data'], 'juno_status' );
	      });
	    }
	};


	function register_events(Jupyter, events) {
	    // If a kernel already exists, create a widget manager.
	    if (Jupyter.notebook && Jupyter.notebook.kernel) {
	        handle_kernel(Jupyter, Jupyter.notebook.kernel);
	    }
	    // When the kernel is created, create a widget manager.
	    events.on('kernel_created.Kernel kernel_created.Session', function(event, data) {
	        handle_kernel(Jupyter, data.kernel);
	    });
	}



	function add_css(url) {
	  $('<link/>')
	      .attr({
	          rel: 'stylesheet',
	          href: window.require.toUrl(url),
	          type: 'text/css'
	      })
	      .appendTo('head');
	}

	function load_ipython_extension () {
	    return new Promise(function(resolve) {
	        requirejs([
	            "base/js/namespace",
	            "base/js/events",
	            'react', 
	            'react-dom', 
	            'components'
	        ], function( Jupyter, events, React, ReactDom, components ) {

	            window.React = React;
	            window.ReactDom = ReactDom;
	            window.Juno = { components };

	            add_css('./nbextensions/juno_magic/juno.css');
	            $('#kernel_indicator').append('<span id="juno_status"></span>');

	            register_events(Jupyter, events);
	            console.log("loaded juno");
	            resolve();
	        });
	    });
	}

	module.exports = {
	  load_ipython_extension: load_ipython_extension
	};


/***/ },
/* 1 */
/***/ function(module, exports, __webpack_require__) {

	var Component = __webpack_require__(2);

	module.exports = function( target, kernel ) {

	    this.components = {};

	    kernel.comm_manager.register_target( target, function( comm, msg ) {
	      if ( msg['msg_type'] === 'comm_open' ) {
	        this.components[ comm.comm_id ] = new Component( comm, msg['content']['data'] );
	      }
	    });

	    return this;
	};


/***/ },
/* 2 */
/***/ function(module, exports) {

	// Generic Component that handles comm messages and renders components to notebook cells

	module.exports = function Component( comm, props, domId ) {

	  var handle_msg = function( msg ) {
	    var data = msg.content.data;    

	    if ( props.module && Juno.components[ props.module ] ) {
	      switch ( data.method ) {
	        case "update":
	          var element = _createMarkup( props.module, data );
	          _render( element, msg );
	          break;
	        case "display":
	          var element = _createMarkup( props.module, props );
	          _render( element, msg );
	          break;
	      }
	    }
	  };

	  var _render = function( element, msg ){ 
	    var display;
	    if ( domId ) {
	      display = document.getElementById( domId );
	    } else {
	      display = _outputAreaElement( msg );
	    }
	    ReactDom.render( element, display );
	  };


	  var _createMarkup = function( mod, newProps ){
	    return React.createElement( Juno.components[ mod ], newProps );
	  };


	  // TODO this is sketchy
	  // improve lookup of msg cell's "output_area.output_subarea" 
	  var _outputAreaElement = function( msg ) {
	    var msg_id = msg.parent_header.msg_id;
	    var parentEl = Jupyter.notebook.get_msg_cell( msg_id ).output_area.element[0];
	    var output_area = parentEl.children[0];
	    return output_area.children[1];
	  }

	  comm.on_msg( handle_msg );
	  return this;
	};


/***/ }
/******/ ])});;