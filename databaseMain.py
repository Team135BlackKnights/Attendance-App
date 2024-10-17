import sqlite3 as sql
from datetime import datetime

def createTable():
    conn = sql.connect('data.db')
    c = conn.cursor()
    print('Connection Secured')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance
              (id INTEGER, name TEXT, date TEXT)
              ''')
    
    conn.commit()
    conn.close()

def writeId(currentId):
    conn = sql.connect('data.db')
    c = conn.cursor()

    c.execute(' INSERT INTO attendance (id) VALUES (?) ', (currentId,))
    conn.commit()
    conn.close()


def writeName(currentId, currentName):
    conn = sql.connect('data.db')
    c = conn.cursor()

    c.execute('UPDATE attendance SET name = (?) WHERE id = (?) ', (currentName, currentId,))
    conn.commit()
    conn.close()

def writeDate(currentId, currentDate):
    conn = sql.connect('data.db')
    c = conn.cursor()

    c.execute('UPDATE attendance SET date = (?) WHERE id = (?) ', (currentDate, currentId,))
    
    conn.commit()
    conn.close()

def getId(id):
    conn = sql.connect('data.db')
    c = conn.cursor()

    c.execute(' SELECT id FROM attendance WHERE id = ?', (id,))
    result = c.fetchone()
    c.close()
    return result[0] if result else None

def getName(id):
    conn = sql.connect('data.db')
    c = conn.cursor()

    c.execute(' SELECT name FROM attendance WHERE id = ?', (id,))
    result = c.fetchone()
    c.close()
    return result[0] if result else None

def getDate(id):
    conn = sql.connect('data.db')
    c = conn.cursor()

    c.execute(' SELECT date FROM attendance WHERE id = ?', (id,))
    result = c.fetchone()
    c.close()
    return result[0] if result else None



