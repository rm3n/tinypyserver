#!/usr/bin/env python3


# no support for ssl/wss
# not scalable
# uses ineff. thread to handle
# no limit on file service/danger

# Other - SSL:
# openssl genrsa -des3 -out server.orig.key 2048
# openssl rsa -in server.orig.key -out server.key
# openssl req -new -key server.key -out server.csr
# openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt
# openssl req -new -x509 -days 365 -nodes -out cert.pem -keyout cert.pem

# Other - Links:
# https://github.com/enthought/Python-2.7.3/blob/master/Lib/SimpleHTTPServer.py
# https://github.com/enthought/Python-2.7.3/blob/master/Lib/SimpleHTTPServer.py
# https://blog.anvileight.com/posts/simple-python-http-server/
# https://gist.github.com/bradmontgomery/2219997
# https://github.com/enthought/Python-2.7.3/blob/master/Lib/BaseHTTPServer.py
# https://www.afternerd.com/blog/python-http-server/
# https://www.acmesystems.it/python_http
# https://github.com/pikhovkin/simple-websocket-server/blob/master/simple_websocket_server/__init__.py

import socket
import hashlib
import base64
import time
import logging
import sys
import ssl
from threading import Thread

if sys.version_info[0] < 3:
    raise Exception("Must be using Python 3")

__responses = {
    100: ('Continue', 'Request received, please continue'),
    101: ('Switching Protocols',
          'Switching to new protocol; obey Upgrade header'),

    200: ('OK', 'Request fulfilled, document follows'),
    201: ('Created', 'Document created, URL follows'),
    202: ('Accepted',
          'Request accepted, processing continues off-line'),
    203: ('Non-Authoritative Information', 'Request fulfilled from cache'),
    204: ('No Content', 'Request fulfilled, nothing follows'),
    205: ('Reset Content', 'Clear input form for further input.'),
    206: ('Partial Content', 'Partial content follows.'),

    300: ('Multiple Choices',
          'Object has several resources -- see URI list'),
    301: ('Moved Permanently', 'Object moved permanently -- see URI list'),
    302: ('Found', 'Object moved temporarily -- see URI list'),
    303: ('See Other', 'Object moved -- see Method and URL list'),
    304: ('Not Modified',
          'Document has not changed since given time'),
    305: ('Use Proxy',
          'You must use proxy specified in Location to access this '
          'resource.'),
    307: ('Temporary Redirect',
          'Object moved temporarily -- see URI list'),

    400: ('Bad Request',
          'Bad request syntax or unsupported method'),
    401: ('Unauthorized',
          'No permission -- see authorization schemes'),
    402: ('Payment Required',
          'No payment -- see charging schemes'),
    403: ('Forbidden',
          'Request forbidden -- authorization will not help'),
    404: ('Not Found', 'Nothing matches the given URI'),
    405: ('Method Not Allowed',
          'Specified method is invalid for this resource.'),
    406: ('Not Acceptable', 'URI not available in preferred format.'),
    407: ('Proxy Authentication Required', 'You must authenticate with '
          'this proxy before proceeding.'),
    408: ('Request Timeout', 'Request timed out; try again later.'),
    409: ('Conflict', 'Request conflict.'),
    410: ('Gone',
          'URI no longer exists and has been permanently removed.'),
    411: ('Length Required', 'Client must specify Content-Length.'),
    412: ('Precondition Failed', 'Precondition in headers is false.'),
    413: ('Request Entity Too Large', 'Entity is too large.'),
    414: ('Request-URI Too Long', 'URI is too long.'),
    415: ('Unsupported Media Type', 'Entity body in unsupported format.'),
    416: ('Requested Range Not Satisfiable',
          'Cannot satisfy request range.'),
    417: ('Expectation Failed',
          'Expect condition could not be satisfied.'),

    500: ('Internal Server Error', 'Server got itself in trouble'),
    501: ('Not Implemented',
          'Server does not support this operation'),
    502: ('Bad Gateway', 'Invalid responses from another server/proxy.'),
    503: ('Service Unavailable',
          'The server cannot process the request due to a high load'),
    504: ('Gateway Timeout',
          'The gateway server did not receive a timely response'),
    505: ('HTTP Version Not Supported', 'Cannot fulfill request.'),
}

# class FileTemplate(Template):
#     def __init__(self, file):
#         pass

class PythonWebInterface(Thread):
    # every connection is handled with a thread, may not scale well, but very easy to deal with
    class ServiceHandlerThread(Thread):
        def __init__(self, socket, address, server):
            Thread.__init__(self)
            self.socket = socket
            self.address = address
            self.path = None
            self.server = server
            self.daemon = True

        def ResolveEndpoint(self):
            self.headers = []

            # just about enough to understand the content
            request = self.socket.recv(4 * 1024)

            # primary headers extraction
            n_index = 0
            parse = True
            request_Content_Length = None
            request_Content_Type = None
            request_Content_Type_Charset = None
            while len(request) > 0 and parse:
                i = n_index
                n_index = request.index(b'\r\n', n_index)
                if i == n_index:
                    parse = False
                else:
                    header = (request[i:n_index]).decode('ascii')
                    if header.startswith('Content-Length:'):
                        request_Content_Length = int(header.split()[1])

                    if header.startswith('Content-Type: application/x-www-form-urlencoded'):
                        request_Content_Type = 'application/x-www-form-urlencoded'
                        request_Content_Type_Charset = 'utf-8'

                    if header.startswith('Content-Type: multipart/form-data'):
                        request_Content_Type = 'multipart/form-data'
                        request_Content_Boundary = header.split()[2].split('=')[1]

                    self.headers.append(header)
                n_index = n_index + len(b'\r\n')

            # additional parsing
            if request_Content_Type and request_Content_Type == 'application/x-www-form-urlencoded':
                self.request_form = request[n_index:]
                while len(self.request_form) < request_Content_Length:
                    self.request_form = self.request_form + self.socket.recv(4 * 1024)

            # https://www.w3.org/TR/html401/interact/forms.html#h-17.13.4
            # yea, not easy, boundry might change, making things more complicated
            if request_Content_Type and request_Content_Type == 'multipart/form-data':
                raise NotImplementedError
                self.content = request[n_index:]
                while len(self.content) < request_Content_Length:
                    self.content = self.content + self.socket.recv(4 * 1024)

            self.command, self.route, self.version = None, None, None

            # extracting verb, route, version
            if len(self.headers) > 0:
                logging.info(self.headers[0])
                words = self.headers[0].split()
                if len(words) == 3:
                    self.command, self.route, self.version = words
                elif len(words) == 2:
                    self.command, self.route = words

            # routing the request/find the correct endpoint
            endpoint = None
            if self.route != None:
                endpoint = self.server.defaultendpoint
                if self.route in self.server.endpoints:
                    endpoint = self.server.endpoints[self.route]

            return endpoint

        def run(self):
            try:
                endpoint = self.ResolveEndpoint()

                if endpoint:
                    endpoint.Respond(self)
                else:
                    raise NotImplementedError

                self.socket.close()

            except Exception as ex:
                logging.critical(ex)
                self.socket.close()

    class Endpoint(object):
        def __init__(self, route, callback):
            self.route = route
            self.callback = callback

        def Respond(self, sockth):
            pass

    class WebStaticEndpoint(Endpoint):
        def __init__(self, path):
            self.route = '*'
            self.path = path
            logging.info('content path : ' + self.path)

        def Respond(self, sockth):
            try:
                with open(self.path + sockth.route, 'rb') as f:
                    content = f.read(16*1024*1024)
                    contentlen = len(content)
                    
            except FileNotFoundError:
                sockth.socket.send(b'HTTP/1.1 404 Not Found\r\n')
                return
                    
            if contentlen == 16*1024*1024:
                raise NotImplementedError
                
            mime = 'application/octet-stream'
            
            # use import mimetypes if gets complicated
            if sockth.route.endswith(".html"):
                mime = 'text/html'
            elif sockth.route.endswith(".ico"):
                mime = 'image/x-icon'
            elif sockth.route.endswith(".css"):
                mime = 'text/css'
            elif sockth.route.endswith(".jpg"):
                mime = 'image/jpeg'
            elif sockth.route.endswith(".js"):
                mime = 'application/javascript'
            elif sockth.route.endswith(".mp4"):
                mime = 'video/mp4'

            sockth.socket.send(b'HTTP/1.1 200 OK\r\n')
            sockth.socket.send(b'Content-Type: ' + bytes(mime, "ascii") + b'\r\n')
            sockth.socket.send(b'Content-Length: ' + bytes(str(contentlen), "ascii") + b'\r\n')
            sockth.socket.send(b'Connection: Closed\r\n')
            sockth.socket.send(b'\r\n')
            sockth.socket.send(content)
    
    class WebServiceEndpoint(Endpoint):
        def __init__(self, route, callback):
            self.route = route
            self.callback = callback

        def Respond(self, sockth):
            self.OnReady(sockth)

        def OnReady(self, sockth):
            pl = sockth.request_form.decode('utf-8')
            pl_parsed = dict(item.split("=") for item in pl.split("&"))
            # urlparse.parse_qs("Name1=Value1;Name2=Value2;Name3=Value3")
            method = self.callback
            content = method(**pl_parsed)
            contentlen = bytes(str(len(content)), "ascii")
            sockth.socket.send(b'HTTP/1.1 200 OK\r\n')
            sockth.socket.send(b'Content-Length: ' + contentlen + b'\r\n')
            sockth.socket.send(b'Connection: Closed\r\n')
            sockth.socket.send(b'\r\n')
            if content != None:
                sockth.socket.send(content)

    # https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
    # * IE, Edge Not supported
    # event: A string identifying the type of event described. If this is specified, an event will be dispatched on the browser to the listener for the specified event name;
    #       the website source code should use addEventListener() to listen for named events. The onmessage handler is called if no event name is specified for a message.
    # data: The data field for the message. When the EventSource receives multiple consecutive lines that begin with data:,
    #       it will concatenate them, inserting a newline character between each one. Trailing newlines are removed.
    # id: The event ID to set the EventSource object's last event ID value.
    #       retry: The reconnection time to use when attempting to send the event. This must be an integer, specifying the reconnection time in milliseconds.
    #       If a non-integer value is specified, the field is ignored.
    class ServerSentEventEndpoint(Endpoint):
        def __init__(self, route):
            super().__init__(route, None)

        def Respond(self, sockth):
            sockth.socket.send(b'HTTP/1.1 200 OK\r\n')
            sockth.socket.send(b'Content-Type: text/event-stream\r\n')
            sockth.socket.send(b'Cache-Control: no-cache\r\n')
            sockth.socket.send(b'\r\n')
            self.OnReady(sockth)

        def Send(self, sockth, id, event, data, retry):
            if id:
                sockth.socket.send(b'id: ' + id + b'\r\n')
            if event:
                sockth.socket.send(b'event: ' + event + b'\r\n')
            if data:
                sockth.socket.send(b'data: ' + data + b'\r\n')
            if retry:
                sockth.socket.send(b'retry: ' + retry + b'\r\n')

            sockth.socket.send(b'\r\n')

        def OnReady(self, sockth):
            while 1:
                self.Send(sockth, None, None,
                          b'Server Side Event - onmessage', None)
                time.sleep(1)
                self.Send(sockth, None, b'customevent',
                          b'Server Side Event - customevent', None)
                time.sleep(1)

    class WebSocketEndpoint(Endpoint):
        def __init__(self, route, onReady):
            self.__MAGICSTRING = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
            self.route = route
            self.onReady = onReady

        def Respond(self, sockth):
            key = [s for s in sockth.headers if "Sec-WebSocket-Key" in s]
            if len(key) == 1:
                skey = key[0].split(':')[1].strip()
                stoken = skey + self.__MAGICSTRING
                stokensha1 = hashlib.sha1(stoken.encode('utf-8'))
                secWebSocketAccept = base64.b64encode(stokensha1.digest())
                sockth.socket.send(b'HTTP/1.1 101 Switching Protocols\r\n')
                sockth.socket.send(b'Upgrade: websocket\r\n')
                sockth.socket.send(b'Connection: Upgrade\r\n')
                sockth.socket.send(b'Sec-WebSocket-Accept: ' + secWebSocketAccept + b'\r\n')
                sockth.socket.send(b'\r\n')
            self.OnReady(sockth)

        def Receive(self, sockth):
            # partial recv looks like wont happen, how ever multiple packets may need to be received and combined
            request = sockth.socket.recv(4096)
            fin = request[0] & 0x80 == 128
            opcode = request[0] & (0xF)
            Mask = request[1] & 0x80 == 128

            payload = bytearray()
            plMask = None
            plFlag = request[1] & 0x7F
            plLen = 0
            plStart = 0

            if plFlag < 126:
                plLen = plFlag
                plStart = 2
                if Mask:
                    plMask = [request[2], request[3], request[4], request[5]]
                    plStart = 2 + 4

            elif plFlag == 126:
                plLen = (request[2] << 8) + request[3]
                plStart = 4
                if Mask:
                    plMask = [request[4], request[5], request[6], request[7]]
                    plStart = 4 + 4

            elif plFlag == 127:
                plLen = (request[2] << 24) + (request[3] <<
                                              16) + (request[4] << 8) + request[5]
                plStart = 6
                if Mask:
                    plMask = [request[6], request[7], request[8], request[9]]
                    plStart = 6 + 4

            i = 0
            for b in request[plStart:]:
                if Mask:
                    payload.append(b ^ plMask[i % 4])
                else:
                    payload.append(b)
                i = i + 1
                plLen = plLen - 1
            return payload

        def Send(self, sockth, payload):
            pllen = len(payload)
            plbytes = bytearray()
            b1, b2 = 0, 0
            opcode = 0x1
            fin = 1
            b1 = opcode | fin << 7

            if pllen < 125:
                b2 |= pllen
            elif pllen > 124:
                raise NotImplementedError

            plbytes.append(b1)
            plbytes.append(b2)
            plbytes.extend(payload)
            sockth.socket.send(plbytes)

        def OnReady(self, sockth):
            while 1:
                response = self.Receive(sockth)
                if response != None:
                    self.Send(sockth, response)

    def __init__(self, hostname, port = 80, cert = None):
        Thread.__init__(self)
        self.endpoints = {}
        self.defaultendpoint = None
        self.hostname = hostname
        self.port = port
        self.daemon = True
        self.listening = False
        self.cert = cert

    def RegisterEndpoint(self, endpoint, default = False):
        logging.debug('registering endpoint ' + endpoint.route)
        self.endpoints[endpoint.route] = endpoint

        if default:
            self.defaultendpoint = endpoint

        return endpoint

    def stop(self):
        """
        properly kills the process: https://stackoverflow.com/a/16736227/4225229
        """
        self.listening = False
        time.sleep(1)
        # connect again to release the listener for terminating the connection
        t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        t.connect((self.hostname, self.port))
        t.close()

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as socksrvr:
            socksrvr.bind((self.hostname, self.port))
            socksrvr.listen(5)  # max backlog of connections
            self.listening = True

            logging.info('listening on ' + self.hostname + ':' + str(self.port))

            while self.listening:
                try:
                    sockclint, addr = socksrvr.accept()
                    
                    if self.cert:
                        sockclint = ssl.wrap_socket(sockclint, certfile = self.cert, server_side = True)

                    logging.debug('connect ' + ':'.join(str(x) for x in addr))
                    PythonWebInterface.ServiceHandlerThread(sockclint, addr, self).start()
    
                except Exception as ex:
                    logging.critical(ex)

                    if self.cert:
                        # client rejects the certifcate?
                        if ex.args[1].startswith('[SSL: SSLV3_ALERT_CERTIFICATE_UNKNOWN]'):
                            continue

                        # a regular socket was connect to secure endpoint
                        if ex.args[1].startswith('[SSL: HTTP_REQUEST]'):
                            continue

                    socksrvr.close()
                    break


if __name__ == '__main__':
    def TestSocket(payload):
        p = payload.decode("ascii")
        logging.debug(p)
        return bytes(p, "utf-8")

    def TestAjax(param1, param2, param3):
        logging.debug('%s %s %s ', param1, param2, param3)
        return b'Ajax Response'

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - [%(levelname)-5.5s] - %(message)s')

    pwui = PythonWebInterface('', 65120)

    pwui.RegisterEndpoint(PythonWebInterface.WebServiceEndpoint('/TestAjax', TestAjax))

    ws = pwui.RegisterEndpoint(PythonWebInterface.WebSocketEndpoint('/TestSocket', TestSocket))
    # ws.OnReady = TestCustomOnReady
    
    sse = pwui.RegisterEndpoint(PythonWebInterface.ServerSentEventEndpoint('/TestSSE'))

    from os import path as ospath
    wse = pwui.RegisterEndpoint(PythonWebInterface.WebStaticEndpoint(ospath.dirname(ospath.abspath(__file__))+ '/contents'), True)
    pwui.start()

    logging.debug('http://localhost:' + str(pwui.port) + '/PythonWebInterface.html')
    logging.info('Press Ctrl+C to terminate.')

    try:
        pwui.join()
    except KeyboardInterrupt:
        logging.debug('closing server')
        pwui.stop()
        pwui.join()