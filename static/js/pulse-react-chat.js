(function(){
'use strict';
if(!window.React||!window.ReactDOM){return;}
var R=window.React,h=R.createElement;
function App(){
var agent=new URLSearchParams(location.search).get('agent')==='codex'?'codex':'claude';
var storageKey='pulse_react_chats_'+agent;
var [chats,setChats]=R.useState(function(){try{var x=JSON.parse(localStorage.getItem(storageKey)||'[]');return Array.isArray(x)?x:[]}catch(e){return []}});
var [active,setActive]=R.useState(null),[draft,setDraft]=R.useState(''),[busy,setBusy]=R.useState(false),[status,setStatus]=R.useState('Ready'),[mobile,setMobile]=R.useState(false);
var scroll=R.useRef(null),poll=R.useRef(null),activeRef=R.useRef(null);
R.useEffect(function(){if(chats.length&&!active){setActive(chats[0].id)}},[]);
R.useEffect(function(){try{localStorage.setItem(storageKey,JSON.stringify(chats.slice(0,30)))}catch(e){}},[chats]);
R.useEffect(function(){if(scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight},[chats,busy,active]);
R.useEffect(function(){return function(){if(poll.current)clearInterval(poll.current)}},[]);
var selected=chats.find(function(c){return c.id===active});
function create(){if(busy)return;var id=Date.now().toString(36)+Math.random().toString(36).slice(2,7);setChats(function(prev){return [{id:id,title:'New chat',messages:[]},...prev]});setActive(id);setMobile(false);setDraft('');setStatus('Ready')}
function change(id){if(busy)return;setActive(id);setMobile(false)}
function addMessage(id,msg){setChats(function(prev){return prev.map(function(c){if(c.id!==id)return c;var msgs=c.messages.concat([msg]);return Object.assign({},c,{messages:msgs,title:c.messages.length===0&&msg.role==='user'?msg.content.slice(0,45):c.title})})})}
function finish(id,reply,success){if(poll.current){clearInterval(poll.current);poll.current=null}addMessage(id,{role:'assistant',content:reply});setBusy(false);setStatus(success?'Ready':'Agent error')}
async function check(job,id){try{var response=await fetch('/api/agents/jobs/'+encodeURIComponent(job),{cache:'no-store'});var data=await response.json();if(!response.ok)throw Error(data.error||'HTTP '+response.status);if(data.status==='running'){setStatus('Thinking…');return}finish(id,data.output||'(No response returned)',data.status==='done')}catch(e){finish(id,'Could not retrieve agent response: '+e.message,false)}}
async function send(value){var prompt=(value||draft).trim();if(!prompt||busy)return;var id=active;if(!id){id=Date.now().toString(36);setChats(function(prev){return [{id:id,title:prompt.slice(0,45),messages:[]},...prev]});setActive(id)}var previous=selected?selected.messages.slice(-6).map(function(m){return (m.role==='user'?'User: ':'Assistant: ')+m.content.slice(0,450)}).join('\n\n'):'';var context=previous?'Previous conversation context:\n'+previous+'\n\nLatest user request:\n'+prompt:prompt;if(context.length>4000)context=context.slice(-4000);addMessage(id,{role:'user',content:prompt});setDraft('');setBusy(true);setStatus('Starting '+agent+'…');try{var response=await fetch('/api/agents/run',{method:'POST',headers:{'Content-Type':'application/json','X-AI-Coding-Center':'1'},body:JSON.stringify({agent:agent,prompt:context})});var data=await response.json();if(!response.ok)throw Error(data.error||'HTTP '+response.status);await check(data.job_id,id);poll.current=setInterval(function(){check(data.job_id,id)},1800)}catch(e){finish(id,'Request failed: '+e.message,false)}}
function button(label,props){return h('button',Object.assign({type:'button'},props),label)}
var messages=selected?selected.messages:[];
return h('div',{className:'app react-ui'},
h('aside',{className:'sidebar'+(mobile?' mobile-open':'')},
h('div',{className:'sidebar-head'},h('div',{className:'brand'},'◈ PULSE'),button('✕',{className:'new mobile-only',onClick:function(){setMobile(false)}})),
h('a',{className:'nav',href:'/'},'← Dashboard'),
button('＋ New chat',{className:'new',onClick:create}),
h('div',{className:'sessions'},chats.length?chats.map(function(c){return button(c.title,{key:c.id,className:'session'+(c.id===active?' active':''),onClick:function(){change(c.id)}})}):h('p',{className:'empty'},'Your conversations will appear here.')),
h('p',{className:'note'},'Conversation history is saved in this browser. CLI execution uses read-only / plan mode.')),
h('main',{className:'main'},
h('header',{className:'top'},
h('div',null,button('☰',{className:'new mobile-only',onClick:function(){setMobile(true)}}),h('div',{className:'title'},agent==='codex'?'Codex':'Claude Code'),h('div',{className:'subtle'},status)),
h('div',{className:'switch'},h('a',{className:agent==='claude'?'active':'',href:'/agents?agent=claude'},'✳ Claude'),h('a',{className:agent==='codex'?'active':'',href:'/agents?agent=codex'},'⌘ Codex'))),
h('div',{className:'messages',ref:scroll},h('div',{className:'inner'},
messages.length===0?h('div',{className:'welcome'},h('div',{className:'agent-badge'},agent==='codex'?'⌘ Codex CLI':'✳ Claude Code CLI'),h('h1',null,'What can I help you build?'),h('p',null,'Your AI coding agent, connected to your Ubuntu VM.'),h('div',{className:'chips'},['Explain this code','Review a security issue','Plan a new feature','Help debug my project'].map(function(q){return button(q,{key:q,className:'chip',onClick:function(){setDraft(q)}})}))):messages.map(function(m,i){return h('div',{className:'message '+m.role,key:i},m.role==='assistant'?h('span',{className:'avatar'},agent==='codex'?'⌘':'✳'):null,h('div',{className:'bubble'},m.content,m.role==='assistant'?h('div',null,button('Copy',{className:'copy',onClick:function(){navigator.clipboard&&navigator.clipboard.writeText(m.content)}})):null))}),
busy?h('div',{className:'message assistant'},h('span',{className:'avatar'},'✦'),h('div',{className:'typing'},h('span',null,'● ● ● '),' Working on your request…')):null)),
h('div',{className:'composer-wrap'},
h('form',{className:'composer',onSubmit:function(ev){ev.preventDefault();send()}},h('textarea',{value:draft,maxLength:4000,rows:2,placeholder:'Message '+(agent==='codex'?'Codex':'Claude')+'…',onChange:function(ev){setDraft(ev.target.value)},onKeyDown:function(ev){if(ev.key==='Enter'&&!ev.shiftKey){ev.preventDefault();send()}}}),button('↑',{type:'submit',className:'send',disabled:busy||!draft.trim(),'aria-label':'Send message'})),
h('p',{className:'hint'},'Enter to send · Shift+Enter for new line · Local CLI agent'))));
}
try{window.ReactDOM.createRoot(document.getElementById('react-app')).render(h(App))}catch(e){console.error('React UI unavailable; original chat remains usable.',e)}
})();