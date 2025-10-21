from django.db import connection
from django.utils.deprecation import MiddlewareMixin
import logging

logger = logging.getLogger(__name__)

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
    
    def process_exception(self, request, exception):
        """
        Close the database connection even when exceptions occur.
        This prevents connection leaks when views raise unhandled exceptions.
        """
        try:
            connection.close()
            logger.debug("Closed database connection after exception")
        except Exception as e:
            logger.error(f"Error closing database connection in exception handler: {e}")
        
        # Return None to let Django handle the exception normally
        return None 