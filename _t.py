import httpx, time
B="http://127.0.0.1:8799"
SID=httpx.post(B+"/api/sessions").json()["id"]
def chat(m, voice=False):
    t=time.time(); r=httpx.post(B+"/api/chat", json={"message":m,"session_id":SID,"voice_mode":voice}, timeout=180).json()
    print(f"[{time.time()-t:4.1f}s] {m!r} -> {r['skill_id']}: {r['reply'][:200]!r}")
chat("what reminders do I have?")
chat("remind me to buy milk")
mo=httpx.get(B+"/api/memory/overview").json(); print(mo["counts"], mo["errors"])
print(httpx.get(B+"/api/notifications").json()[:2])
print(httpx.post(B+f"/api/sessions/{SID}/clear").json())
chat("what is my name?", True)
