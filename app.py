# app.py - Web wrapper para Render
# Arranca el bot en un hilo en segundo plano y expone un endpoint HTTP simple.

from threading import Thread
from flask import Flask
import oanda_timebot

app = Flask(__name__)

def start_worker():
    # ejecuta el loop infinito del bot
    oanda_timebot.run()

# Lanzamos el worker al importar el módulo (1 proceso/worker)
worker = Thread(target=start_worker, daemon=True)
worker.start()

@app.route("/")
def index():
    return "OK"
