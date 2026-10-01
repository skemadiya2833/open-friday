import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

type Skill = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  triggers: string[];
};

type View = "chat" | "memory" | "skills" | "tasks" | "settings";

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<{ role: string; text: string; skill?: string }[]>([
    { role: "assistant", text: "Friday React shell online. Prefer /public UI if you have not run npm build — both talk to the same API." },
  ]);
  const [input, setInput] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [skillChip, setSkillChip] = useState<string | null>(null);
  const [state, setState] = useState("idle");

  useEffect(() => {
    fetch("/api/skills").then((r) => r.json()).then(setSkills).catch(() => {});
  }, []);

  async function send() {
    if (!input.trim()) return;
    const text = input;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setState("thinking");
    let sid = sessionId;
    if (!sid) {
      const s = await (await fetch("/api/sessions", { method: "POST" })).json();
      sid = s.id;
      setSessionId(sid);
    }
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sid }),
    });
    const data = await res.json();
    setSessionId(data.session_id);
    const selected = (data.events || []).find((e: any) => e.type === "skill_selected");
    if (selected) setSkillChip(selected.skill_id);
    setMessages((m) => [...m, { role: "assistant", text: data.reply, skill: data.skill_id }]);
    setState("idle");
  }

  return (
    <div className="app">
      <aside className="rail">
        <div className="brand">
          <motion.div
            className="orb"
            animate={{ scale: state === "thinking" ? [1, 1.15, 1] : 1 }}
            transition={{ repeat: state === "thinking" ? Infinity : 0, duration: 1 }}
          />
          <div>
            <strong>Friday</strong>
            <div className="muted">{state}</div>
          </div>
        </div>
        {(["chat", "memory", "skills", "tasks", "settings"] as View[]).map((v) => (
          <button key={v} className={view === v ? "active" : ""} onClick={() => setView(v)}>
            {v}
          </button>
        ))}
      </aside>
      <main>
        <AnimatePresence mode="wait">
          {view === "chat" && (
            <motion.section key="chat" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              {skillChip && <div className="chip">Skill · {skillChip}</div>}
              <div className="messages">
                {messages.map((m, i) => (
                  <div key={i} className={`bubble ${m.role}`}>
                    {m.skill && <div className="muted">{m.skill}</div>}
                    {m.text}
                  </div>
                ))}
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send();
                }}
              >
                <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Message Friday…" />
                <button type="submit">Send</button>
              </form>
            </motion.section>
          )}
          {view === "skills" && (
            <motion.section key="skills" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <h1>Skills</h1>
              {skills.map((s) => (
                <div key={s.id} className="card">
                  <h3>{s.name}</h3>
                  <p>{s.description}</p>
                  <p className="muted">{s.enabled ? "enabled" : "disabled"}</p>
                </div>
              ))}
            </motion.section>
          )}
          {view !== "chat" && view !== "skills" && (
            <motion.section key={view} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <h1>{view}</h1>
              <p className="muted">Use the built-in Control Center at the server root (public/) for the full {view} UI, or extend this React shell.</p>
            </motion.section>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}
