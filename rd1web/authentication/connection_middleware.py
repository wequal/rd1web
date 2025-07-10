from django.db import connection
from django.utils.deprecation import MiddlewareMixin

class DBConnectionMiddleware(MiddlewareMixin):
    """
    This middleware explicitly closes the database connection after each request.
    It can help prevent "database has gone away" or "server closed the connection unexpectedly"
    errors by ensuring that connections are not left open.
    This is especially useful in environments with long-running application servers
    or strict database connection timeouts.
    """
    def process_response(self, request, response):
        """
        Close the database connection after the response has been prepared.
        """
        connection.close()
        return response 