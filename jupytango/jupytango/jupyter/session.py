# ===========================================================================
#  This file is part of the Tango Ecosystem
#
#  Copyright 2017-EOT Synchrotron SOLEIL, St.Aubin, France
#
#  This is free software: you can redistribute it and/or modify it under the
#  terms of the GNU Lesser General Public License as published by the Free
#  Software Foundation, either version 3 of the License, or (at your option)
#  any later version.
#
#  This is distributed in the hope that it will be useful, but WITHOUT ANY
#  WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
#  FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for
#  more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with This.  If not, see <http://www.gnu.org/licenses/>.
# ===========================================================================

"""jupytango"""

from __future__ import print_function

import logging
from threading import Lock
from collections import deque
from uuid import uuid4

from IPython.display import HTML, display, publish_display_data

from bokeh.io import output_notebook, curstate, show
from bokeh.resources import Resources
from bokeh.application import Application
from bokeh.application.handlers import Handler, FunctionHandler
from bokeh.embed import server_document
from bokeh.util.notebook import EXEC_MIME_TYPE, HTML_MIME_TYPE

from tools import JupyterContext, get_jupyter_context

module_logger_name = "jupytango.jupyter.session"

# ------------------------------------------------------------------------------
class BokehSessionHandler(Handler):
    def on_server_loaded(self, server_context):
        pass

    def on_server_unloaded(self, server_context):
        pass

    def on_session_created(self, session_context):
        pass

    def on_session_destroyed(self, session_context):
        pass

    def modify_document(self, doc):
        return doc


# ------------------------------------------------------------------------------
class BokehSession(object):
    __repo__ = dict()
    __repo_lock__ = Lock()

    __logger__ = logging.getLogger(module_logger_name)

    def __init__(self, uuid=None):
        # session identifier
        self._uuid = uuid if uuid else str(uuid4().hex)
        # the session info
        self._info = None
        # the associated bokeh document (for experts only)
        self._doc = None
        # periodic callback period in seconds - defaults to None (i.e. disabled)
        self._callback_period = None
        # periodic activity enabled?
        self._suspended = True
        # is this session closed?
        self._closed = False
        # close existing session: this is a way to avoid leaks & resources waste
        self.__close_existing_session(self._uuid)
        # insert new session into the repo
        with BokehSession.__repo_lock__:
            BokehSession.__repo__[self._uuid] = self
        BokehSession.print_repository_status()

    def __close_existing_session(self, uuid):
        with BokehSession.__repo_lock__:
            try:
                session = BokehSession.__repo__[uuid]
                session.close()
            except KeyError:
                pass
            except Exception as e:
                BokehSession.__logger__.error(e)
            finally:
                try:
                    del BokehSession.__repo__[uuid]
                except KeyError:
                    pass
                except Exception as e:
                    BokehSession.__logger__.error(e)

    def _on_session_created(self, session_info):
        self._info = session_info
        self._doc = session_info['doc']
        self.setup_document()

    def _on_session_created_backup(self, doc):
        self._doc = doc
        self.setup_document()

    def _on_session_destroyed(self):
        pass

    @property
    def uuid(self):
        return self._uuid

    @property
    def ready(self):
        return self._doc is not None

    @property
    def server(self):
        return self._info['server']

    @property
    def document(self):
        return self._doc

    @property
    def bokeh_session(self):
        return self._info['server'].get_sessions('/')[0]

    @property
    def bokeh_session_id(self):
        return self._doc.session_context.id if self._doc else None

    @property
    def suspended(self):
        return self._suspended

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
        BokehServer.open_session(self)

    def close(self, async=True):
        """close the session"""
        self.cleanup(async)

    def cleanup(self, async=True):
        """cleanup the session"""
        # TODO: async cleanup required but might not be safe!
        self.pause()
        if async:
            self.safe_document_modifications(self.__cleanup)
        else:
            self.__cleanup()
        
    def __cleanup(self):
        """asynchronous close"""
        # TODO: async close required but might not be safe!
        try:
            if self._doc:
                self._doc.clear()
            BokehServer.close_session(self)
        except Exception as e:
            BokehSession.__logger__.error(e)
        finally:
            self._closed = True
            with BokehSession.__repo_lock__:
                try:
                    del BokehSession.__repo__[self._uuid]
                except:
                    pass
            BokehSession.print_repository_status()

    def setup_document(self):
        """give the session a chance to setup the freshy created bokeh document"""
        pass

    def periodic_callback_enabled(self):
        """return True if the periodic callback is enabled, return False otherwise"""
        return not self.callback_period == None

    def periodic_callback(self):
        """periodic callback (default impl. does nothing)"""
        pass

    def start(self):
        """start the periodic activity (if any)"""
        self.resume()

    def stop(self):
        """stop the periodic activity (if any)"""
        self.pause()

    def pause(self):
        """suspend the (periodic) callback"""
        self.__set_callback_period(None)
        self._suspended = True

    def resume(self):
        """resume the (periodic) callback"""
        self.__set_callback_period(self.callback_period)
        self._suspended = False

    def update_callback_period(self, cbp):
        self.callback_period = cbp
        self.__set_callback_period(cbp)

    def __set_callback_period(self, cbp):
        try:
            self.document.remove_periodic_callback(self.periodic_callback)
        except:
            pass
        if cbp is not None:
            self.document.add_periodic_callback(self.periodic_callback, max(100, int(1000. * cbp)))

    def timeout_callback(self, cb, tmo):
        """call the specified callback after expiration of the specified timeout (in seconds)"""
        if self.ready:
            self._doc.add_timeout_callback(cb, int(1000. * tmo))

    def safe_document_modifications(self, cb):
        """call the specified callback in the a context in which the session document is locked"""
        if self.ready:
            self._doc.add_next_tick_callback(cb)

    def __repr__(self):
        return "BokehSession:{}:{}".format(self._uuid, ('closed' if self._closed else 'opened'))

    @staticmethod
    def close_all():
        with BokehSession.__repo_lock__:
            for s in BokehSession.__repo__.values():
                try:
                    s.close()
                except Exception as e:
                    BokehSession.__logger__.error('failed to close BokehSession:{}'.format(s.uuid))

    @staticmethod
    def print_repository_status():
        with BokehSession.__repo_lock__:
            if len(BokehSession.__repo__):
                BokehSession.__logger__.info(
                    'BokehSession.repository. contains {} session(s):'.format(len(BokehSession.__repo__)))
                for s in BokehSession.__repo__.values():
                    BokehSession.__logger__.info('- {}'.format(s))
            else:
                BokehSession.__logger__.info('BokehSession.repository is empty')


# ------------------------------------------------------------------------------
class BokehServer(object):
    #TODO: cleanup the code
    __bkh_srv__ = None
    __srv_url__ = None
    __srv_id__ = None
    __srv_lock__ = Lock()

    __sessions__ = deque()
    __sessions_lock__ = Lock()

    __logger__ = logging.getLogger(module_logger_name)

    __running_in_jupyterlab__ = True

    __jcontext__ = None

    @staticmethod
    def __spawn_server():
        import socket
        from tornado.ioloop import IOLoop
        from bokeh.server.server import Server
        logging.getLogger('tornado').setLevel(logging.ERROR)  # TODO: tmp stuff
        logging.getLogger('bokeh.server.tornado').setLevel(logging.ERROR)  # TODO: tmp stuff
        logging.getLogger('bokeh.server.util').setLevel(logging.ERROR)  # TODO: tmp stuff
        output_notebook(Resources(mode='inline', components=["bokeh", "bokeh-gl"]), hide_banner=True)
        app = Application(FunctionHandler(BokehServer.__session_entry_point))
        app.add(BokehSessionHandler())
        srv = Server({'/': app}, io_loop=IOLoop.current(), port=0, allow_websocket_origin=['*'])
        srv_id = uuid4().hex
        curstate().uuid_to_server[srv_id] = srv
        srv_addr = srv.address if srv.address else socket.gethostbyname(socket.gethostname())
        srv_url = 'http://{}:{}/'.format(srv_addr, srv.port)
        srv.start()
        return {'server': srv, 'server_id': srv_id, 'server_url': srv_url, 'application': app}

    @staticmethod
    def open_session(new_session):
        BokehServer.__logger__.debug("BokehServer.open_session <<")
        assert (isinstance(new_session, BokehSession))
        with BokehServer.__srv_lock__:
            BokehServer.__logger__.debug("BokehServer.open_session.spawning server")
            srv_info = BokehServer.__spawn_server()
            BokehServer.__logger__.debug("BokehServer.open_session.server spawn")
        with BokehServer.__sessions_lock__:
            session_info = srv_info
            session_info['session'] = new_session
            BokehServer.__sessions__.appendleft(session_info)
        script = server_document(url=srv_info['server_url'])
        if get_jupyter_context() == JupyterContext.LAB:
            BokehServer.__logger__.info("BokehServer.open_session:running in JupyterContext.LAB")
            data = {HTML_MIME_TYPE: script, EXEC_MIME_TYPE: ""}
            metadata = {EXEC_MIME_TYPE: {"server_id": srv_info['server_id']}}
            publish_display_data(data, metadata=metadata)
        else:
            BokehServer.__logger__.info("BokehServer.open_session:running in JupyterContext.NOTEBOOK")
            display(HTML(script))
        BokehServer.__logger__.debug("BokehServer.open_session >>")

    @staticmethod
    def __session_entry_point(doc):
        try:
            BokehServer.__logger__.debug("BokehServer.session_entry_point <<")
            with BokehServer.__sessions_lock__:
                session_info = BokehServer.__sessions__.pop()
            session = session_info['session']
            session_info['doc'] = doc
            session._on_session_created(session_info)
        except Exception as e:
            BokehServer.__logger__.error(e)
        finally:
            BokehServer.__logger__.debug("BokehServer.session_entry_point >>")
            return doc

    @staticmethod
    def server_singleton___start_server():
        import socket
        from tornado.ioloop import IOLoop
        from bokeh.server.server import Server
        BokehServer.__jcontext__ = get_jupyter_context()
        logging.getLogger('bokeh.server.util').setLevel(logging.ERROR)  # TODO: tmp stuff
        output_notebook(Resources(mode='inline', components=["bokeh", "bokeh-gl"]), hide_banner=True)
        app = Application(FunctionHandler(BokehServer.__session_entry_point))
        app.add(BokehSessionHandler())
        srv = Server({'/': app}, io_loop=IOLoop.current(), port=0, allow_websocket_origin=['*'])
        BokehServer.__bkh_srv__ = srv
        BokehServer.__srv_id__ = uuid4().hex
        curstate().uuid_to_server[BokehServer.__srv_id__] = srv
        srv_addr = srv.address if srv.address else socket.gethostbyname(socket.gethostname())
        BokehServer.__srv_url__ = 'http://{}:{}/'.format(srv_addr, srv.port)
        BokehServer.__bkh_srv__.start()

    @staticmethod
    def server_singleton_open_session(new_session):
        BokehServer.__logger__.debug("BokehServer.open_session <<")
        assert (isinstance(new_session, BokehSession))
        with BokehServer.__srv_lock__:
            if not BokehServer.__bkh_srv__:
                BokehServer.__logger__.debug("BokehServer.open_session.starting server")
                BokehServer.__start_server()
                BokehServer.__logger__.debug("BokehServer.open_session.server started")
        with BokehServer.__sessions_lock__:
            session_info = {'session': new_session, 'application': None}
            BokehServer.__sessions__.appendleft(session_info)
        script = server_document(url=BokehServer.__srv_url__)
        if BokehServer.__jcontext__ == JupyterContext.LAB:
            data = {HTML_MIME_TYPE: script, EXEC_MIME_TYPE: ""}
            metadata = {EXEC_MIME_TYPE: {"server_id": BokehServer.__srv_id__}}
            publish_display_data(data, metadata=metadata)
        else:  # running in jupyter notebbok
            display(HTML(script))
        BokehServer.__logger__.debug("BokehServer.open_session >>")

    @staticmethod
    def server_singleton___session_entry_point(doc):
        try:
            BokehServer.__logger__.debug("BokehServer.session_entry_point <<")
            with BokehServer.__sessions_lock__:
                session_info = BokehServer.__sessions__.pop()
            session = session_info['session']
            session._on_session_created(session_info['application'], doc)
        except Exception as e:
            BokehServer.__logger__.error(e)
        finally:
            BokehServer.__logger__.debug("BokehServer.session_entry_point >>")
            return doc

    @staticmethod
    def close_session(session):
        BokehServer.__logger__.debug("BokehServer.close_session <<")
        assert (isinstance(session, BokehSession))
        # TODO: is the document.clear called from the BokeSession.__cleanup is enough
        # TODO: to release every single resource associated with the session?
        BokehServer.__logger__.debug("BokehServer.close_session >>")
