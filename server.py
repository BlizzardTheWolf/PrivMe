from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import socket
import threading

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

SERVER_HOST = '0.0.0.0'
SERVER_PORT = 5556
USERNAME_MAX_LENGTH = 20

encryption_key = None
username = None

def derive_key(password):
    """Derive an AES encryption key from the password."""
    salt = b'\x00' * 16
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=default_backend()
    )
    return kdf.derive(password.encode())

def encrypt_message(message):
    """Encrypt a message using AES encryption."""
    if not isinstance(message, str):
        raise ValueError("Message must be a string.")
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(encryption_key), modes.CFB(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_message = iv + encryptor.update(message.encode('utf-8')) + encryptor.finalize()
    return encrypted_message

def decrypt_message(encrypted_message):
    """Decrypt a message using AES encryption."""
    try:
        iv = encrypted_message[:16]
        cipher = Cipher(algorithms.AES(encryption_key), modes.CFB(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_message = decryptor.update(encrypted_message[16:]) + decryptor.finalize()
        return decrypted_message.decode('utf-8')
    except UnicodeDecodeError:
        return "[ERROR: Unable to decode message]"

class ChatClient:
    def __init__(self):
        self.client_socket = None

    def connect(self):
        """Connect to the chat server."""
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((SERVER_HOST, SERVER_PORT))
            self.client_socket.send("UML".encode('utf-8'))
            server_response = self.client_socket.recv(1024).decode('utf-8', errors='ignore')
            return server_response
        except Exception as e:
            return str(e)

    def send_username(self, username):
        """Send the username to the server."""
        try:
            self.client_socket.send(username.encode('utf-8'))
        except (BrokenPipeError, OSError):
            emit('message', {'username': 'System', 'message': 'Connection to server lost.'})

    def send_encrypted_message(self, encrypted_message):
        """Send an encrypted message to the server."""
        try:
            self.client_socket.send(encrypted_message)
        except (BrokenPipeError, OSError):
            emit('message', {'username': 'System', 'message': 'Connection to server lost. Message could not be sent.'})

    def listen_to_server(self):
        """Listen for messages from the server."""
        while True:
            try:
                data = self.client_socket.recv(1024)
                if data:
                    if data.startswith(b"Server:"):
                        socketio.emit('message', {'username': 'System', 'message': data.decode('utf-8', errors='ignore')})
                    else:
                        username, encrypted_message = data.split(b": ", 1)
                        message = decrypt_message(encrypted_message)
                        socketio.emit('message', {'username': username.decode('utf-8'), 'message': message})
            except (BrokenPipeError, OSError):
                socketio.emit('message', {'username': 'System', 'message': 'Disconnected from server.'})
                break

chat_client = ChatClient()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/username_requirements")
def username_requirements():
    return jsonify({
        "max_length": USERNAME_MAX_LENGTH,
        "no_spaces": True,
        "non_empty": True
    })

@socketio.on('join')
def handle_join(data):
    global encryption_key, username

    username = data['username']
    password = data['password']
    
    if not username or len(username) > USERNAME_MAX_LENGTH or " " in username:
        emit('message', {'username': 'System', 'message': f"Username must be 1-{USERNAME_MAX_LENGTH} characters long and contain no spaces."})
        return

    encryption_key = derive_key(password)
    
    server_response = chat_client.connect()
    if "Error" in server_response:
        emit('message', {'username': 'System', 'message': f'Failed to connect to server: {server_response}'})
        return

    chat_client.send_username(username)

    if not hasattr(chat_client, 'joined') or not chat_client.joined:
        chat_client.joined = True
        threading.Thread(target=chat_client.listen_to_server, daemon=True).start()
        emit('message', {'username': 'System', 'message': f'You joined the chat as <b>{username}</b>.'})
    else:
        pass

@socketio.on('send_message')
def handle_send_message(data):
    message = data['message']
    encrypted_message = encrypt_message(message)
    chat_client.send_encrypted_message(encrypted_message)
    emit('message', {'username': 'You', 'message': message}, broadcast=True)

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
