from __future__ import print_function

import socket

from collections import deque

import numpy as np

from IPython.display import HTML, clear_output, display

from tornado.ioloop import IOLoop
from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers import Handler, FunctionHandler
from bokeh.embed import autoload_server
from bokeh.io import reset_output


class BokehSessionHandler(Handler):

    def on_server_loaded(self, server_context):
        print("SessionHandler: on_server_loaded <<")
        pass
        print("SessionHandler: on_server_loaded >>")

    def on_server_unloaded(self, server_context):
        print("SessionHandler: on_server_unloaded <<")
        pass
        print("SessionHandler: on_server_unloaded >>")

    def on_session_created(self, session_context):
        print("SessionHandler: on_session_created <<")
        pass
        print("SessionHandler: on_session_created >>")

    def on_session_destroyed(self, session_context):
        print("SessionHandler: on_server_unloaded <<")
        pass
        print("SessionHandler: on_server_unloaded >>")


class BokehSession(object):
    
    def __init__(self):
        """the associated bokeh document (for experts only)"""
        self._doc = None
        """periodic callback period in seconds - defaults to None (i.e. disabled)"""
        self._callback_period = None

    def on_session_created(self, doc):
        self._doc = doc
        self.setup_document()

    def on_session_destroyed():
        pass
        
    @property
    def ready(self):
        return self._doc is not None

    @property
    def document(self):
        return self._doc

    @property
    def id(self):
        return self._doc.session_context.id if self._doc else None

    @property 
    def callback_period(self):
        """return the (periodic) callback period in seconds or None (i.e. disabled)"""
        return self._callback_period

    @callback_period.setter 
    def callback_period(self, ucbp):
        """set the (periodic) callback period in seconds or None to disable the callback"""
        self._callback_period = max(0.1, ucbp) if ucbp is not None else None

    def open(self):
        """open the session"""
        print("BokehSession.open <<")
        BokehServer.open_session(self)
        print("BokehSession.open >>")

    def close(self):
        """close the session"""
        BokehServer.close_session(self)
        
    def setup_document(self):
        """give the session a chance to setup the freshy created bokeh document"""
        pass

    def periodic_callback(self):
        """periodic callback (default impl. does nothing)"""
        pass
  
    def pause(self):
        """suspend the (periodic) callback"""
        BokehServer.update_callback_period(self, None)
    
    def resume(self):
        """resume the (periodic) callback"""
        BokehServer.update_callback_period(self, self.callback_period)

    def update_callback_period(self, ucbp):
        """update the (periodic) callback"""
        self.callback_period = ucbp
        BokehServer.update_callback_period(self, self.callback_period)

    def safe_document_modifications(self, cb):
        """call the specified callback in the a context in which the session document is locked"""
        if self._doc:
            self._doc.add_next_tick_callback(cb)


class BokehServer(object):

    __bkh_app__ = None
    __bkh_srv__ = None
    __srv_url__ = None
    __sessions__ = deque()
        
    @staticmethod
    def __start_server():
        app = Application(FunctionHandler(BokehServer.__entry_point))
        app.add(BokehSessionHandler())
        srv = Server(
            {'/': app},
            io_loop=IOLoop.instance(),
            port=0,
            host='*',
            allow_websocket_origin=['*']
        )
        srv.start()
        srv_addr = srv.address if srv.address else socket.gethostbyname(socket.gethostname())
        BokehServer.__bkh_srv__ = srv
        BokehServer.__bkh_app__ = app
        BokehServer.__srv_url__ = 'http://{}:{}'.format(srv_addr, srv.port)
        
    @staticmethod
    def __entry_point(doc):
        try:
            #TODO: should we lock BokehServer.__sessions__? 
            print('BokehServer.__entry_point <<')
            session = BokehServer.__sessions__.pop() 
            session.on_session_created(doc)
            print('BokehServer.__entry_point >>')
        except Exception as e:
            print(e)
        
    @staticmethod
    def __add_periodic_callback(session, ucbp):
        assert(isinstance(session, BokehSession))
        pcb = session.periodic_callback
        try:
            session.document.remove_periodic_callback(pcb)
        except:
            pass
        if ucbp is not None:
            session.document.add_periodic_callback(pcb, max(100, 1000. * ucbp))
        
    @staticmethod
    def open_session(new_session):
        print("BokehServer.open_session <<")
        assert(isinstance(new_session, BokehSession))
        if not BokehServer.__bkh_srv__:
            print("BokehServer.open_session.starting server")
            BokehServer.__start_server()
            print("BokehServer.open_session.server started")
        #TODO: should we lock BokehServer.__sessions__? 
        BokehServer.__sessions__.appendleft(new_session) 
        print("BokehServer.open_session.autoload server from {}".format(BokehServer.__srv_url__))
        script = autoload_server(model=None, url=BokehServer.__srv_url__)
        html_display = HTML(script)
        display(html_display)
        print("BokehServer.open_session >>")
        
    @staticmethod
    def close_session(session):
        """totally experimental attempt to destroy a session from python!"""
        assert(isinstance(session, BokehSession))
        session_id = session._doc.session_context.id
        session = BokehServer.__bkh_srv__.get_session('/', session_id)
        session.destroy()
        
    @staticmethod
    def update_callback_period(session, ucbp):
        assert(isinstance(session, BokehSession))
        BokehServer.__add_periodic_callback(session, ucbp)
        
    @staticmethod
    def print_info(called_from_session_handler=False):
        if not BokehServer.__bkh_srv__:
            print("no Bokeh server running") 
            return
        try:
            print("Bokeh server URL: {}".format(BokehServer.__srv_url__))
            sessions = BokehServer.__bkh_srv__.get_sessions()
            num_sessions = len(sessions)
            if called_from_session_handler:
                num_sessions += 1
            print("Number of opened sessions: {}".format(num_sessions))
        except Exception as e:
            print(e)


