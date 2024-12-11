import curses as c
import socket
import threading
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os, time, sys

mode = "normal"
if len(sys.argv) > 1:
    if sys.argv[1] == "debug":
        mode = "debug"

class ChatClient:
    def __init__(self):

        self.line = 0
        self.recievedMsgs = []

        server_input = getPromptedInput(1, 0, "Enter server address: ")
        if ':' in server_input:
            host, port = server_input.split(':')
            port = int(port)
        else:
            host = server_input
            port = int(getPromptedInput(1, 0, "Enter server port: "))

        # Establish socket connection
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.connect((host, port))

        self.connectedHost = host
        self.connectedPort = port
        self.users = []

        # Ask server for Max Username Length
        self.client_socket.send("UML".encode())
        server_response = self.client_socket.recv(1024).decode('utf-8')

        # Check response
        if server_response.startswith("USERNAME_MAX_LENGTH:"):
            self.username_max_length = int(server_response.split(":")[1])
            displayText(1, 0, f"Username may not contain spaces. MAX {self.username_max_length} chars")
        else:
            displayText(1, 0, "ERROR: Failed to retrieve some server settings")
            self.client_socket.close()
            return

        # Send the username unencrypted

        self.client_socket.send("GETUSERS".encode())
        users = self.client_socket.recv(1024).decode('utf-8')

        self.client_socket.send("START".encode())

        while 1:
            self.username = getPromptedInput(2, 0, "Enter your name:")
            if 0 < len(self.username) <= self.username_max_length or " " in self.username:
                break
            clearLine(screen, 1)
            displayText(1, 0, f"Invalid username")

        self.client_socket.send(self.username.encode())

        self.password = getPasswordPromptedInput(1, 0, "Enter encryption password:")
        self.key = self.derive_key(self.password)

    def derive_key(self, password):
        """Derives a 32-byte key from the password."""
        salt = b'\x00' * 16  # Fixed salt for simplicity (should ideally be unique)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        return kdf.derive(password.encode())

    def encrypt_message(self, message):
        """Encrypts the message with AES."""
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self.key), modes.CFB(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        encrypted_message = iv + encryptor.update(message.encode()) + encryptor.finalize()
        return encrypted_message

    def decrypt_message(self, encrypted_message):
        """Decrypts the incoming AES-encrypted message."""
        iv = encrypted_message[:16]
        cipher = Cipher(algorithms.AES(self.key), modes.CFB(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_message = decryptor.update(encrypted_message[16:]) + decryptor.finalize()
        return decrypted_message.decode()

    def receive_messages(self):
        """Receive and decrypt messages from the server."""
        while True:
            try:
                data = self.client_socket.recv(1024)
                if not data:
                    break

                if data.startswith(b"Server:"):
                    message = data.decode('utf-8').replace("Server: ", "")
                    msg = f"{time.strftime('%H:%M:%S', time.gmtime(time.time()))} SERVER: {message}"
                    displayMsg(msg)
                # Separate username and message

                elif data.startswith(b"UserUpdate:"):
                    self.users = data.decode('utf-8').replace("UserUpdate: ", "")
                    clearLine(screen, 1)
                    self.users = formatUsers(self.users)
                    updateUsers(self.users)

                else:
                    username, encrypted_message = data.split(b": ", 1)
                    # Attempt decryption, handle errors
                    try:
                        message = self.decrypt_message(encrypted_message)
                        username = username.decode('utf-8')
                        msg = f"{time.strftime('%H:%M:%S', time.gmtime(time.time()))} {username}: {message}"
                        displayMsg(msg)
                    except Exception as e:
                        if mode == "debug":
                            clearLine(screen, 1)
                            displayText(1, 0, f"ERROR: {e}")
            except Exception as e:
                print(f"Connection error: {e}")
                break

    def send_messages(self):
        """Encrypt and send messages to the server."""
        while True:
            message = getPromptedInput(screen.getmaxyx()[0]-1, 0, f"SEND MESSAGE TO {self.connectedHost}:{self.connectedPort}:")
            if message == None:
                continue
            if message.lower() == "exit":
                self.client_socket.close()
                break
            encrypted_message = self.encrypt_message(message)
            self.client_socket.send(encrypted_message)
            msg = f"{time.strftime('%H:%M:%S', time.gmtime(time.time()))} you: {message}"
            displayMsg(msg)

    def run(self):
        """Run the client by starting sender and receiver threads."""
        threading.Thread(target=self.receive_messages, daemon=True).start()
        self.send_messages()

#------------------------------------------------------------------------------
#------------------------------------------------------------------------------
screen = c.initscr()
c.noecho()
c.cbreak()
screen.keypad(True)

#Get an input at position x and y
def getInput(screenPositionY, screenPositionX):
    unusedKeys = ["KEY_DC", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_HOME", "KEY_PPAGE", "KEY_NPAGE", "KEY_IC", "KEY_END", "KEY_SR", "KEY_SF", "KEY_SLEFT", "KEY_SRIGHT"]

    message = ""
    y, x = screenPositionY, screenPositionX
    maxSize = screen.getmaxyx()

    if x >= maxSize[1] or y >= maxSize[0]:
        raise ValueError(f"cannot write outside or on screen borders: {maxSize!r}")

    while (1):
        key = screen.getkey()
        keyw = key

        if key == "\n":
            return(message)

        if key == "KEY_RESIZE":
            resize()
            return None

        if key in unusedKeys: continue

        if key == "KEY_BACKSPACE" or key == "\b" or key == chr(127):
            x-=1
            if x < screenPositionX and y==screenPositionY: x = screenPositionX
            if x == -1:
                y-=1
                x=screen.getmaxyx()[1]-1
            keyw = " "
            message = message[:-1]

        if x == maxSize[1] and key != "KEY_BACKSPACE" and key != chr(127):
            y+=1
            x=0

        screen.addstr(y, x, keyw)


        if key != "KEY_BACKSPACE" and key != "\b" and key != chr(127):
            x+=1
            message += keyw
        else: screen.move (y, x)

#get an input without showing at x and y
def getPasswordInput(screenPositionY, screenPositionX):
    unusedKeys = ["KEY_DC", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_HOME", "KEY_PPAGE", "KEY_NPAGE", "KEY_IC", "KEY_END", "KEY_RESIZE"]
    message = ""
    y, x = screenPositionY, screenPositionX
    maxSize = screen.getmaxyx()

    if x >= maxSize[1] or y >= maxSize[0]:
        raise ValueError(f"cannot write outside or on screen borders: {maxSize!r}")

    while (1):
        key = screen.getkey()
        keyw = key

        if key == "\n":
            return(message)

        if key in unusedKeys: continue

        if key == "KEY_BACKSPACE" or key == "\b" or key == chr(127):
            x-=1
            if x < screenPositionX and y==screenPositionY: x = screenPositionX
            if x == -1:
                y-=1
                x=screen.getmaxyx()[1]-1
            keyw = " "
            message = message[:-1]

        if x == screen.getmaxyx()[1] and key != "KEY_BACKSPACE" and key != chr(127):
            y+=1
            x=0

        #screen.addstr(y, x, keyw)


        if key != "KEY_BACKSPACE" and key != "\b" and key != chr(127):
            x+=1
            message += keyw

#get input with text at x and y
def getPromptedInput(screenPositionY, screenPositionX, prompt):
    displayText(screenPositionY, screenPositionX, prompt)
    renturnVal = getInput(screenPositionY, screenPositionX+len(prompt)+1)
    screen.move(screenPositionY, 0)
    screen.clrtoeol()
    return renturnVal

#get input with text without showing at x and y
def getPasswordPromptedInput(screenPositionY, screenPositionX, prompt):
    clearLine(screen, screenPositionY)
    displayText(screenPositionY, screenPositionX, prompt)
    renturnVal = getPasswordInput(screenPositionY, screenPositionX+len(prompt)+1)
    clearLine(screen, screenPositionY)
    return renturnVal

#show some text on the screen at position x and y
def displayText(screenPositionY, screenPositionX, text):
    screen.addstr(screenPositionY, screenPositionX, text)
    screen.refresh()

#display the messages curretly in the buffer
def displayMsg(msg):
    app.recievedMsgs.append(msg)
    if 5+app.line == screen.getmaxyx()[0]-3:
        for i in range(len(app.recievedMsgs)):
            clearUntil(screen, screen.getmaxyx()[0]-3-i, screen.getmaxyx()[1]-(screen.getmaxyx()[1]//5))
            displayText(screen.getmaxyx()[0]-3-i, 0, app.recievedMsgs[len(app.recievedMsgs)-1-i])
        app.recievedMsgs.pop(0)
    else:
        clearUntil(screen, 5+app.line, screen.getmaxyx()[1]-(screen.getmaxyx()[1]//5))
        displayText(5+app.line, 0, msg)
        app.line += 1

def resize():
    screenSetup(1)
    updateUsers(app.users)
    for i in app.recievedMsgs:
        displayMsg(i)


def clearLine(scr, screenPositionY):
    scr.move(screenPositionY, 0)
    scr.clrtoeol()

def clearUntil(scr, screenPositionY, stopX):
    scr.move(screenPositionY, 0)
    displayText(screenPositionY, 0, " "*stopX)

def formatUsers(users):
    usernames = []
    tick = 0
    pos = -1
    for i in range(len(users)):
        if users[i] == "'" and tick == 1:
            usernames.append(users[pos+1:i])
            tick = 0
            pos = -1
        elif users[i] == "'":
            pos = i
            tick = 1
    return usernames

def updateUsers(users):
    usableX = screen.getmaxyx()[1]//5
    if usableX < 11: return
    startX = screen.getmaxyx()[1]-usableX
    usercount = len(users)

    for i in range(4, screen.getmaxyx()[0]-2):
        displayText(i, startX, " "*usableX)

    if len(users) > screen.getmaxyx()[0]-6:
        users = users[0:screen.getmaxyx()[0]-7]
        users.append("...")

    displayText(4, startX, f"Users({usercount}):")
    for i in range(len(users)):
        if len(users[i]) > usableX:
            users[i] = users[i][0:usableX-3]
            users[i] += "..."
        displayText(5+i, startX, users[i])

def screenSetup(connection):
    screen.clear()
    if screen.getmaxyx()[0] < 10 or screen.getmaxyx()[1] < 30:
        exit(49)
    if screen.getmaxyx()[1] >= 50:
        displayText(0, screen.getmaxyx()[1]-14, "PRIVME TUI V1")

    if connection == 1:
        displayText(0, 0, f"CONNECTED TO {app.connectedHost}:{app.connectedPort} as {app.username}")
        displayText(3, 0, f"FEED FROM {app.connectedHost}:{app.connectedPort}:")

        for i in range(screen.getmaxyx()[1]-1):
            displayText(4, i, "_")
            displayText(screen.getmaxyx()[0]-2, i, "_")

try:
    screenSetup(0)

    app = ChatClient()

    screenSetup(1)

    app.run()

finally:
    c.echo()
    screen.keypad(False)
    c.endwin()
