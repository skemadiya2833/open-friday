"""Local test site for browser and canvas benchmark tasks.

Every page posts what the user did to /api/event with the run token, so the success check is a
server-side fact ("the server saw 3 clicks on Increment"), not something the agent claims.
Binds to 127.0.0.1 on a random port; serves only these fixed pages.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_HEAD = """<!doctype html><meta charset=utf-8><title>{title}</title>
<style>body{{font:20px Segoe UI,sans-serif;margin:30px}} button{{font-size:20px;padding:8px 18px;margin:6px}}
input,select{{font-size:20px;padding:6px}} canvas{{border:2px solid #444;background:#fafafa}}</style>
<script>
const T=new URLSearchParams(location.search).get('t')||'';
function ev(kind,data){{fetch('/api/event',{{method:'POST',headers:{{'Content-Type':'application/json'}},
 body:JSON.stringify(Object.assign({{token:T,kind:kind}},data||{{}})),keepalive:true}});}}
</script>"""


def _page(title: str, body: str) -> bytes:
    return (_HEAD.format(title=title) + f"<h1>{title}</h1>" + body).encode()


PAGES = {
    "/counter": lambda: _page("Counter test", """
<p>Count: <span id=count>0</span></p>
<button id=inc onclick="c=(window.c||0)+1;window.c=c;document.getElementById('count').textContent=c;ev('inc',{n:c})">Increment</button>"""),
    "/form": lambda: _page("Name form", """
<label>Name <input id=name aria-label="Name"></label>
<button id=submit onclick="ev('submit',{name:document.getElementById('name').value});document.title='Submitted'">Submit</button>"""),
    "/select": lambda: _page("Preferences", """
<p><label>Favorite color <select id=color aria-label="Favorite color"><option>Red</option><option>Green</option><option>Blue</option></select></label></p>
<p><label><input type=checkbox id=agree> I agree</label></p>
<button id=submit onclick="ev('submit',{color:document.getElementById('color').value,agree:document.getElementById('agree').checked})">Save preferences</button>"""),
    "/long": lambda: _page("Long page", """
<p>Scroll down to find the button at the very bottom.</p><div style="height:2600px"></div>
<button id=bottom onclick="ev('bottom_click')">Reached the bottom</button>"""),
    "/nav1": lambda: _page("Page one", """
<p><a id=next href="#" onclick="location.href='/nav2?t='+T;return false">Go to page 2</a></p>"""),
    "/nav2": lambda: _page("Page two", """
<button id=confirm onclick="ev('confirm')">Confirm</button>"""),
    "/canvas_click": lambda: _page("Canvas click", """
<p>Click the <b>red circle</b>. (Blue square is a decoy.)</p><canvas id=c width=900 height=450></canvas>
<script>
const c=document.getElementById('c'),g=c.getContext('2d');
g.fillStyle='#d22';g.beginPath();g.arc(620,170,45,0,7);g.fill();
g.fillStyle='#22d';g.fillRect(150,260,100,100);
c.addEventListener('click',e=>{const r=c.getBoundingClientRect(),x=(e.clientX-r.left)*c.width/r.width,y=(e.clientY-r.top)*c.height/r.height;
 let hit='none'; if(Math.hypot(x-620,y-170)<=45)hit='red'; else if(x>=150&&x<=250&&y>=260&&y<=360)hit='blue';
 ev('click',{x:x,y:y,hit:hit});});
</script>"""),
    "/canvas_drag": lambda: _page("Canvas drag", """
<p>Drag from the <b>green dot</b> to the <b>orange dot</b>.</p><canvas id=c width=900 height=450></canvas>
<script>
const c=document.getElementById('c'),g=c.getContext('2d');
function dot(x,y,col){g.fillStyle=col;g.beginPath();g.arc(x,y,16,0,7);g.fill();}
dot(120,225,'#2a2');dot(780,225,'#e80');
function pos(e){const r=c.getBoundingClientRect();return [(e.clientX-r.left)*c.width/r.width,(e.clientY-r.top)*c.height/r.height];}
let s=null;c.addEventListener('mousedown',e=>{s=pos(e);});
c.addEventListener('mouseup',e=>{if(!s)return;const p=pos(e);
 ev('stroke',{start_a:Math.hypot(s[0]-120,s[1]-225)<=30,end_b:Math.hypot(p[0]-780,p[1]-225)<=30,len:Math.hypot(p[0]-s[0],p[1]-s[1])});s=null;});
</script>"""),
    "/canvas_game": lambda: _page("Target game", """
<p>Click the <b>green target</b> 3 times. It moves after each hit.</p><canvas id=c width=900 height=450></canvas>
<script>
const c=document.getElementById('c'),g=c.getContext('2d');const P=[[200,120],[650,300],[420,380],[760,110]];
let n=0;function draw(){g.clearRect(0,0,900,450);const p=P[n%P.length];g.fillStyle='#1b1';g.beginPath();g.arc(p[0],p[1],38,0,7);g.fill();}
draw();
c.addEventListener('click',e=>{const r=c.getBoundingClientRect(),x=(e.clientX-r.left)*c.width/r.width,y=(e.clientY-r.top)*c.height/r.height;
 const p=P[n%P.length];const hit=Math.hypot(x-p[0],y-p[1])<=38;ev('target',{hit:hit,n:n});if(hit){n++;draw();}});
</script>"""),
}


class Site:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._lock = threading.Lock()
        site = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_GET(self):  # noqa: N802
                path = urlparse(self.path).path
                fn = PAGES.get(path)
                if fn is None:
                    self.send_error(404)
                    return
                body = fn()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                if urlparse(self.path).path != "/api/event":
                    self.send_error(404)
                    return
                n = int(self.headers.get("Content-Length", "0") or 0)
                try:
                    data = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                except ValueError:
                    data = {}
                with site._lock:
                    site._events.append(data)
                self.send_response(204)
                self.end_headers()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def url(self, page: str, token: str) -> str:
        return f"http://127.0.0.1:{self.port}/{page}?t={token}"

    def events(self, token: str, kind: str | None = None) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e.get("token") == token and (kind is None or e.get("kind") == kind)]

    def close(self) -> None:
        self.httpd.shutdown()
