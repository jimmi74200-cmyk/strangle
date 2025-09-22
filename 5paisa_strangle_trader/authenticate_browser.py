import http.server
import socketserver
import webbrowser
from urllib.parse import urlparse, parse_qs
import threading
from py5paisa import FivePaisaClient
import config
import os

# Configuration
PORT = 8888
REDIRECT_URL = f"http://localhost:{PORT}/"
request_token = None

# --- Robust File Path ---
script_dir = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(script_dir, 'config.py')
# ------------------------

class TokenHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global request_token
        # Parse the request token from the URL
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        request_token = query_params.get('RequestToken', [None])[0]

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if request_token:
            self.wfile.write(b"<h1>Login Successful!</h1><p>You can now close this browser tab.</p>")
        else:
            self.wfile.write(b"<h1>Login Failed.</h1><p>Could not retrieve token. Please try again.</p>")

        # Shutdown the server after handling the request
        threading.Thread(target=httpd.shutdown).start()

if __name__ == "__main__":
    # Initialize the 5paisa client to get the UserKey
    client = FivePaisaClient(cred={
        "APP_NAME": config.APP_NAME,
        "APP_SOURCE": config.APP_SOURCE,
        "USER_ID": config.USER_ID,
        "PASSWORD": config.PASSWORD,
        "USER_KEY": config.USER_KEY,
        "ENCRYPTION_KEY": config.ENCRYPTION_KEY
    })

    # Construct the login URL
    login_url = f"https://dev-openapi.5paisa.com/WebVendorLogin/VLogin/Index?VendorKey={config.USER_KEY}&ResponseURL={REDIRECT_URL}"

    # Start the local server in a separate thread
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("", PORT), TokenHandler)
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    print(f"Local server started on port {PORT}. Waiting for login...")

    # Open the login URL in the user's browser
    webbrowser.open(login_url)

    # Wait for the server to handle the request and shut down
    server_thread.join()
    print("Local server stopped.")

    if request_token:
        print(f"Successfully captured request token: {request_token}")

        # Exchange the request token for an access token
        access_token = client.get_oauth_session(request_token)

        if access_token:
            print("Login successful!")

            # Read the config file
            with open(config_path, "r") as f:
                lines = f.readlines()

            # Update the access token and client code
            with open(config_path, "w") as f:
                for line in lines:
                    if line.strip().startswith("ACCESS_TOKEN"):
                        f.write(f'ACCESS_TOKEN = "{access_token}"\n')
                    elif line.strip().startswith("CLIENT_CODE"):
                        f.write(f'CLIENT_CODE = "{client.client_code}"\n')
                    else:
                        f.write(line)

            print("Access token and client code have been updated in config.py")
        else:
            print("Failed to get access token.")
    else:
        print("Failed to capture request token.")
