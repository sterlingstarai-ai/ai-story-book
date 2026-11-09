"""Forward two isolated QA listeners without rewriting signed media requests."""

from contextlib import contextmanager
import select
import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading


class _RelayHandler(BaseRequestHandler):
    def handle(self):
        with socket.create_connection(("127.0.0.1", self.server.server_address[1]), timeout=10) as upstream:
            self.request.settimeout(10)
            destinations = {self.request: upstream, upstream: self.request}
            while destinations:
                readable, _, _ = select.select(list(destinations), [], [], 60)
                if not readable:
                    return
                for source in readable:
                    destination = destinations[source]
                    data = source.recv(65536)
                    if data:
                        destination.sendall(data)
                    else:
                        destination.shutdown(socket.SHUT_WR)
                        del destinations[source]


class _ReviewRelay(ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, bind_ip, port, peer_ip):
        self._allowed = {bind_ip, peer_ip}
        super().__init__((bind_ip, port), _RelayHandler)

    def verify_request(self, request, client_address):
        return client_address[0] in self._allowed

    def handle_error(self, request, client_address):
        # A disconnect or timeout must never print HTTP headers or signed URLs.
        return


@contextmanager
def forward_review_port(bind_ip, port, peer_ip):
    """Forward one selected interface/port to the same port on localhost."""
    if bind_ip in {"0.0.0.0", "127.0.0.1"} or not port:
        raise ValueError("A separate interface and explicit review port are required")
    with _ReviewRelay(bind_ip, port, peer_ip) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join()
