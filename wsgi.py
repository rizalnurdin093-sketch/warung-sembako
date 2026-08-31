"""WSGI entry — dipanggil oleh gunicorn/Flask run, mount app di /warung/."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from app import app as flask_app

# Mount app di prefix /warung
application = DispatcherMiddleware(
    flask_app,  # root: redirect ke /warung/login
    {
        '/warung': flask_app
    }
)

if __name__ == '__main__':
    # serve di port 5002 (root context)
    from werkzeug.serving import run_simple
    run_simple('0.0.0.0', 5002, application)
