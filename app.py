import json, os, sqlite3, time
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

from agent_web import agent_web
app.register_blueprint(agent_web)

from token_usage import token_usage
app.register_blueprint(token_usage)
DB = Path(os.environ.get('USAGE_DB', str(Path.home()/'.ai-coding-center'/'usage.sqlite3')))
DB.parent.mkdir(parents=True, exist_ok=True)

def db():
    con=sqlite3.connect(DB)
    con.execute('CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL)')
    return con

@app.get('/')
def home(): return render_template('tokens.html')

@app.get('/api/stats')
def stats():
    with db() as con:
        row=con.execute('SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM usage').fetchone()
        models=con.execute('SELECT model,COUNT(*),SUM(input_tokens),SUM(output_tokens) FROM usage GROUP BY model ORDER BY COUNT(*) DESC LIMIT 10').fetchall()
        recent=con.execute('SELECT timestamp,provider,model,input_tokens,output_tokens FROM usage ORDER BY id DESC LIMIT 15').fetchall()
    return jsonify(requests=row[0],input_tokens=row[1],output_tokens=row[2],models=[dict(zip(('model','requests','input','output'),r)) for r in models],recent=[dict(zip(('time','provider','model','input','output'),r)) for r in recent],source='Local usage database; not connected to FCC automatically',remaining_quota=None)

@app.get('/guide')
def guide(): return render_template('guide.html')

@app.get('/health')
def health(): return {'status':'ok'}

if __name__=='__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT','8765')))
