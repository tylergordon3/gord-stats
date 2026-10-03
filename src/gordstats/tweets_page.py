"""
Tweets of the week: the funniest college football and NFL posts on X, sent in
by readers, picked by the site's owner and voted up by readers.

Home carries a swipeable row of them (home_card(), placed by
cbb.render.render_home under What's new) and /tweets/ the whole week
(generate(), built in the daily run's render-home block). Both are shells: the
posts come from /api/tweets (functions/api/tweets.js) when the page opens, so
a post approved at noon is on Home at noon, not at the next build.

The cards are light on purpose - author, handle, the words, a media badge,
votes - drawn from what X's keyless oEmbed said when the post was sent in.
The post itself (photos, video, X's own markup) is X's embed, and it loads
only when a reader taps a card: X's embed page in a sandboxed iframe, in a
dialog over the page. Never widgets.js and never oEmbed's HTML: either would
run X's script or markup inside this site, where it could act as the
signed-in reader. The iframe keeps X's code on X's origin; the page takes
three things from it - the height, "rendered" and "no results" - and only in
messages from that frame, from X's origin (checked 2026-10-03: X's
Tweet.html posts twttr.private.resize / rendered / no_results to its parent
without widgets.js).

Nothing here moves the page as it loads (the 2026-10-02 layout-shift work):
the row holds its height from the first paint - placeholder cards, then the
posts, the empty state or an error, all the same height - and the submit box
opens only when tapped. With no posts at all the row stays, as the invitation
to send one in: at launch that is the only way anyone finds the feature.

    python -m gordstats.tweets_page
"""
from html import escape

from gordstats import paths
from gordstats.frontmatter import add_front_matter
from gordstats.jsonio import script_json

OUT = paths.DOCS / "tweets" / "index.html"
HOME_MAX = 10        # cards in Home's row; the page has every one the API sends
PAGE_MAX = 40        # functions/api/tweets.js MAX_LIST
# X's own embed page, the one widgets.js would put in an iframe for us.
EMBED = "https://platform.twitter.com/embed/Tweet.html"
# What the embed may do: run its script on its own origin and open X in a new
# tab. Not navigate this page, not submit forms here, not open modals.
SANDBOX = "allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"

HOW = "The last seven days' picks, most votes first. Vote for the ones that got you."

CONFIG = {
    "api": "/api/tweets",
    "embed": EMBED,
    "sandbox": SANDBOX,
    # How long the embed has to say it drew before the dialog says it is
    # blocked: an iframe reports no error for a page that never comes.
    "wait": 15000,
    "sports": {"cfb": "CFB", "nfl": "NFL"},
    "say": "Readers send them in, we pick, you vote.",
    "empty": ("Nothing picked yet this week. Seen a funny college football or NFL post on X? "
              "Send it in – readers vote on the ones we pick."),
    "failed": "Couldn't load the posts just now.",
    "blocked": ("X's post would not load here – a content blocker may be stopping it. "
                "Open it on X instead."),
    "gone": "X would not show this post – it may have been deleted.",
}

CSS = """<style>
.tw{--tw-ink:#0f172a;--tw-text:#1e293b;--tw-line:#e2e8f0;--tw-card:#fff;--tw-act:#1f6fd0;
  --tw-act-ink:#fff;--tw-chip:#f1f5f9;--tw-chip-ink:#334155}
/* Every size below is fixed so the row is the same height whatever fills it:
   placeholders, posts, the empty state or an error. */
.tw-row{display:flex;gap:12px;overflow-x:auto;overflow-y:hidden;height:290px;
  margin:12px -4px 0;padding:2px 4px 0;scroll-snap-type:x mandatory;
  overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch;scrollbar-width:thin}
.tw-row>.tw-card{flex:0 0 min(272px,calc(100% - 44px));scroll-snap-align:start}
/* The page's grid grows with the week, so it starts a screen tall: whatever
   it pushes down was below the fold when it drew. */
.tw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;
  min-height:100vh;align-content:start;margin:14px 0 0}
.tw-card{box-sizing:border-box;height:268px;min-width:0;display:flex;flex-direction:column;
  gap:6px;padding:12px 12px 10px;border:1px solid var(--tw-line);border-radius:12px;
  background:var(--tw-card);box-shadow:0 1px 2px rgba(15,23,42,.05);cursor:pointer;
  text-align:left}
/* On the page the cards take the height of their words: it grows below the
   fold whatever they do (see .tw-grid), and a short post in a phone-wide card
   was mostly white space. */
.tw-grid .tw-card:not(.tw-ghost){height:auto;min-height:168px}
.tw-card.tw-ghost{cursor:default;box-shadow:none;background:linear-gradient(var(--tw-chip),
  var(--tw-chip)) 12px 14px/55% 14px no-repeat,linear-gradient(var(--tw-chip),var(--tw-chip))
  12px 36px/35% 11px no-repeat,linear-gradient(var(--tw-chip),var(--tw-chip)) 12px 66px/
  calc(100% - 24px) 96px no-repeat,var(--tw-card)}
.tw .tw-who{display:flex;flex-direction:column;min-width:0;line-height:1.25}
.tw .tw-name{font-size:14.5px;font-weight:800;color:var(--tw-ink);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.tw .tw-handle{font-size:12.5px;color:var(--gs-muted,#5d6b7e);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
.tw .tw-text{flex:1 1 auto;min-height:0;font-size:14px;line-height:1.4;color:var(--tw-text);
  white-space:pre-line;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:6;
  -webkit-box-orient:vertical;overflow:hidden}
.tw .tw-text i{color:var(--gs-muted,#5d6b7e)}
.tw .tw-badges{display:flex;gap:6px;height:22px;overflow:hidden;align-items:center}
.tw .tw-badge{font-size:12px;font-weight:700;line-height:20px;padding:0 7px;border-radius:999px;
  background:var(--tw-chip);color:var(--tw-chip-ink);white-space:nowrap}
.tw .tw-badge.cfb{background:#fff1e6;color:#9a3412}
.tw .tw-badge.nfl{background:#e8f0fe;color:#1e40af}
.tw .tw-badge.old{background:transparent;border:1px dashed var(--tw-line);line-height:18px;
  color:var(--gs-muted,#5d6b7e)}
.tw .tw-act{display:flex;gap:6px;align-items:center;height:40px}
.tw .tw-act button,.tw .tw-act a,.tw-sub{box-sizing:border-box;display:inline-flex;
  align-items:center;justify-content:center;min-height:40px;padding:0 11px;border-radius:999px;
  font:inherit;font-size:13px;font-weight:700;white-space:nowrap;cursor:pointer;
  text-decoration:none;border:1px solid var(--tw-line);background:transparent;color:var(--tw-ink)}
.tw .tw-act .tw-vote{min-width:58px;border-color:var(--tw-act);color:var(--tw-act);gap:5px}
.tw .tw-act .tw-vote.on{background:var(--tw-act);color:var(--tw-act-ink)}
.tw .tw-act .tw-vote:disabled{opacity:.6;cursor:progress}
.tw .tw-act .tw-x{margin-left:auto;border:0;padding:0 4px;color:var(--tw-act)}
.tw-empty{box-sizing:border-box;flex:1 0 100%;grid-column:1/-1;height:268px;display:flex;
  align-items:center;justify-content:center;text-align:center;padding:16px 22px;
  border:1px dashed #cbd5e1;border-radius:12px;font-size:14.5px;line-height:1.5;
  color:var(--tw-text)}
.tw-foot{display:flex;align-items:center;gap:8px 14px;min-height:40px;margin-top:6px}
.tw-sub{border-color:var(--tw-act);color:var(--tw-act);padding:0 15px;font-size:13.5px}
.tw .tw-say{flex:1 1 auto;min-width:0;margin:0;font-size:12.5px;line-height:1.35;
  color:var(--gs-muted,#5d6b7e);display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;overflow:hidden}
.tw .tw-say a{font-weight:700}
/* The theme gives every form a grey box and 20px of padding. */
.tw .tw-form{margin:10px 0 0;padding:0;background:none}
.tw-form label{display:block;font-size:13px;font-weight:700;color:var(--tw-ink);margin:0 0 5px}
.tw-fields{display:flex;flex-wrap:wrap;gap:8px}
/* 16px: iOS zooms the page into any smaller field it focuses. */
.tw-fields input,.tw-fields select{box-sizing:border-box;min-height:40px;font:inherit;
  font-size:16px;border:1px solid #cbd5e1;border-radius:8px;padding:0 10px;
  background:var(--tw-card);color:var(--tw-ink)}
.tw-fields input{flex:1 1 220px;min-width:0}
.tw-fields .tw-send{min-height:40px;padding:0 18px;border-radius:8px;border:1px solid var(--tw-act);
  background:var(--tw-act);color:var(--tw-act-ink);font:inherit;font-size:14px;font-weight:800;
  cursor:pointer}
.tw-fields .tw-send:disabled{opacity:.6;cursor:progress}
/* Three lines held from the moment the form opens, so an answer arriving
   later pushes nothing under it. */
.tw .tw-said{min-height:3.9em;margin:6px 0 0;font-size:13px;line-height:1.3;color:var(--tw-text)}
.tw .tw-said.ok{color:#15803d}
.tw .tw-said.err{color:#b91c1c}
.tw .tw-intro{margin:0 0 10px;font-size:14.5px;line-height:1.5;color:var(--tw-text);max-width:760px}
.tw-head-r{display:inline-flex;align-items:center;gap:6px}
.tw-nav{display:none}
@media (hover:hover) and (pointer:fine) and (min-width:700px){
  .tw-nav{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;
    border-radius:999px;border:1px solid var(--tw-line);background:transparent;
    color:var(--tw-ink);font-size:20px;line-height:1;cursor:pointer}
}
dialog.tw-dlg{box-sizing:border-box;width:min(560px,calc(100vw - 24px));
  max-height:calc(100vh - 32px);overflow:auto;padding:0;border:0;border-radius:14px;
  background:#fff;color:#0f172a;box-shadow:0 20px 50px rgba(15,23,42,.35)}
dialog.tw-dlg::backdrop{background:rgba(15,23,42,.55)}
.tw-dlg-head{position:sticky;top:0;z-index:1;display:flex;align-items:center;gap:8px;
  justify-content:space-between;padding:4px 4px 4px 16px;background:inherit;
  border-bottom:1px solid #e2e8f0}
.tw-dlg-t{font-size:15px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tw-dlg-x{flex:0 0 40px;width:40px;height:40px;border:0;background:transparent;color:inherit;
  font-size:26px;line-height:1;cursor:pointer}
.tw-dlg-body{padding:8px 12px;min-height:220px}
/* No height until X says how tall the post is: the wait line holds the room. */
.tw-dlg-body iframe.tw-embed{display:block;width:100%;max-width:550px;height:0;margin:0 auto;
  border:0;color-scheme:normal}
.tw-dlg-wait{margin:70px 8px;text-align:center;font-size:14px;color:var(--gs-muted,#5d6b7e)}
.tw-dlg-foot{margin:0;padding:6px 16px 14px;font-size:13.5px}
.tw-dlg-foot a{display:inline-flex;align-items:center;min-height:40px;font-weight:700}
@media (prefers-color-scheme: dark){
  .tw{--tw-ink:#f1f5f9;--tw-text:#dde5ef;--tw-line:#2b3852;--tw-card:#16203a;--tw-act:#7cb4ff;
    --tw-act-ink:#0b1220;--tw-chip:#24314d;--tw-chip-ink:#dde5ef}
  .tw .tw-badge.cfb{background:#3b2410;color:#fdba74}
  .tw .tw-badge.nfl{background:#172554;color:#93c5fd}
  .tw-empty{border-color:#3b4a66}
  .tw-fields input,.tw-fields select{border-color:#3b4a66}
  .tw .tw-said.ok{color:#6ee7b7}
  .tw .tw-said.err{color:#ff9b91}
  dialog.tw-dlg{background:#16203a;color:#f1f5f9}
  .tw-dlg-head{border-bottom-color:#2b3852}
}
</style>"""

JS = """<script>
(function(){
  var CFG=__CFG__;
  var boxes=[].slice.call(document.querySelectorAll('.tw[data-tw]:not([data-tw-on])'));
  if(!boxes.length) return;
  boxes.forEach(function(b){ b.setAttribute('data-tw-on','1'); });
  var ID=/^[1-9][0-9]{0,19}$/, HANDLE=/^[A-Za-z0-9_]{1,15}$/;

  function esc(v){
    return String(v==null?'':v).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});
  }
  // What favorites.js last heard from /api/me ("in", "out", "off"): the
  // submit control starts right, and /api/tweets' own answer settles it.
  var guess=null;
  try{ guess=localStorage.getItem('gs:acct'); }catch(e){}
  var state={configured:guess!=='off', signedIn:guess==='in', byId:{}, rest:esc(CFG.say)};
  var login='/api/auth/login?next='+encodeURIComponent(location.pathname+location.search);

  function xUrl(t){
    return 'https://x.com/'+(HANDLE.test(t.handle||'')?t.handle:'i')+'/status/'+t.tweet_id;
  }
  function voteLabel(n, on){
    return (on?'Remove your vote':'Vote for this post')+' ('+n+(n===1?' vote)':' votes)');
  }
  function card(t){
    var n=Math.max(0, t.votes|0), on=!!t.mine;
    var sp=(t.sport==='cfb'||t.sport==='nfl')?t.sport:'';
    var badges=(sp?'<span class="tw-badge '+sp+'">'+esc(CFG.sports[sp])+'</span>':'')
      +(t.has_media==2?'<span class="tw-badge">&#9654; Video</span>'
        :t.has_media==1?'<span class="tw-badge">&#9635; Photo or video</span>':'')
      +(t.earlier?'<span class="tw-badge old">Earlier</span>':'');
    return '<article class="tw-card" data-id="'+t.id+'">'
      +'<div class="tw-who"><span class="tw-name">'+esc(t.author||(t.handle?'@'+t.handle:'On X'))+'</span>'
      +(t.handle?'<span class="tw-handle">@'+esc(t.handle)+'</span>':'<span class="tw-handle">&nbsp;</span>')+'</div>'
      +'<div class="tw-text">'+(t.text?esc(t.text):'<i>No words, just the picture &ndash; tap to see it.</i>')+'</div>'
      +'<div class="tw-badges">'+badges+'</div>'
      +'<div class="tw-act">'
      +'<button type="button" class="tw-vote'+(on?' on':'')+'" aria-pressed="'+on+'" aria-label="'
      +voteLabel(n,on)+'">&#9650; <span class="tw-n">'+n+'</span></button>'
      +'<button type="button" class="tw-show">Show post</button>'
      +'<a class="tw-x" href="'+esc(xUrl(t))+'" target="_blank" rel="noopener noreferrer">Open on X</a>'
      +'</div></article>';
  }
  function fill(html){
    boxes.forEach(function(b){
      var host=b.querySelector('.tw-list');
      host.innerHTML=typeof html==='function'?html(b):html;
      host.removeAttribute('aria-busy');
    });
  }
  function paintSubmit(){
    boxes.forEach(function(b){
      var go=b.querySelector('.tw-signin'), open=b.querySelector('.tw-open');
      go.href=login;
      // Same height either way, so a guess put right moves nothing.
      go.hidden=!state.configured||state.signedIn;
      open.hidden=!state.configured||!state.signedIn;
    });
  }
  function draw(d){
    d=d||{};
    if(d.configured===false) state.configured=false;
    else if(d.configured) state.configured=true;
    state.signedIn=!!d.signedIn;
    var list=(Array.isArray(d.tweets)?d.tweets:[]).filter(function(t){
      return t&&ID.test(String(t.tweet_id))&&/^[1-9][0-9]{0,11}$/.test(String(t.id));
    });
    state.byId={};
    list.forEach(function(t){ t.tweet_id=String(t.tweet_id); state.byId[t.id]=t; });
    // The owner is told when readers' posts are waiting: the review list is
    // at the foot of /profile/, and nothing else on the site leads to it.
    var waiting=d.admin===true?Math.max(0, d.pending|0):0;
    state.rest=waiting
      ?waiting+(waiting===1?' post':' posts')+' waiting for your review. '
        +'<a href="/profile/#pf-tw">Review</a>'
      :esc(CFG.say);
    boxes.forEach(function(b){ b.querySelector('.tw-say').innerHTML=state.rest; });
    fill(function(b){
      var max=+b.getAttribute('data-max')||list.length;
      return list.length?list.slice(0,max).map(card).join('')
        :'<div class="tw-empty">'+esc(CFG.empty)+'</div>';
    });
    paintSubmit();
  }
  function failed(){ fill('<div class="tw-empty">'+esc(CFG.failed)+'</div>'); }

  var sayTimer=null;
  function say(b, html){
    var el=b.querySelector('.tw-say');
    el.innerHTML=html;
    clearTimeout(sayTimer);
    sayTimer=setTimeout(function(){ el.innerHTML=state.rest; }, 9000);
  }
  function said(el, text, cls, signin){
    el.className='tw-said'+(cls?' '+cls:'');
    el.innerHTML=esc(text)+(signin?' <a href="'+esc(login)+'">Sign in</a>':'');
  }
  function post(url, body){
    return fetch(url,{method:'POST', credentials:'same-origin',
        headers:{'content-type':'application/json'}, body:JSON.stringify(body)})
      .then(function(r){
        return r.json().catch(function(){ return {}; }).then(function(j){
          return {ok:r.ok, status:r.status, j:j||{}};
        });
      }, function(e){
        console.warn('tweets: no answer', e);
        return {ok:false, status:0, j:{error:"Couldn't reach the server. Try again in a minute."}};
      });
  }

  function vote(b, btn){
    var c=btn.closest('.tw-card'), id=c&&c.getAttribute('data-id');
    if(!id||btn.disabled) return;
    if(!state.signedIn){
      say(b,'<a href="'+esc(login)+'">Sign in</a> to vote.');
      return;
    }
    btn.disabled=true;
    post('/api/tweets/'+id+'/vote',{}).then(function(a){
      if(a.ok&&a.j.ok){ setVote(id, a.j.votes|0, !!a.j.mine); return; }
      if(a.status===401){
        state.signedIn=false; paintSubmit();
        say(b,'<a href="'+esc(login)+'">Sign in</a> to vote.');
        return;
      }
      say(b, esc(a.j.error||'That vote did not go through.'));
    }).then(function(){ btn.disabled=false; });
  }
  function setVote(id, n, on){
    var t=state.byId[id];
    if(t){ t.votes=n; t.mine=on; }
    [].forEach.call(document.querySelectorAll('.tw-card[data-id="'+id+'"] .tw-vote'),function(v){
      v.classList.toggle('on', on);
      v.setAttribute('aria-pressed', String(on));
      v.setAttribute('aria-label', voteLabel(n, on));
      v.querySelector('.tw-n').textContent=n;
    });
  }

  function send(b){
    var f=b.querySelector('.tw-form'), input=f.querySelector('.tw-url'),
        sport=f.querySelector('.tw-sport'), btn=f.querySelector('.tw-send'),
        out=f.querySelector('.tw-said');
    var url=input.value.trim();
    if(!url){ said(out,'Paste the link to a post on X first.','err'); input.focus(); return; }
    btn.disabled=true;
    said(out,'Sending\\u2026','');
    post(CFG.api,{url:url, sport:sport.value||null}).then(function(a){
      if(a.ok&&a.j.ok){
        said(out, a.j.message||"Thanks \\u2013 it's in the queue.",'ok');
        input.value=''; sport.value='';
        // The owner's own go straight on the list: show it there now.
        if(a.j.status==='approved') load();
        return;
      }
      if(a.status===401){
        state.signedIn=false; paintSubmit();
        said(out,'Sign in first, then send it again.','err',true);
        return;
      }
      said(out, a.j.error||('That did not go through ('+a.status+').'), a.status===409?'':'err');
    }).then(function(){ btn.disabled=false; });
  }

  // X's embed, one post at a time in a dialog - the top layer, so nothing on
  // the page moves when it grows - as X's own page in a sandboxed iframe.
  // Its messages are read only from that frame and X's origin, and only for
  // a height and whether the post drew.
  var dlg=null, seq=0, embed=null, EMBED_ORIGIN='';
  try{ EMBED_ORIGIN=new URL(CFG.embed, location.href).origin; }catch(e){}
  window.addEventListener('message',function(e){
    if(!embed||e.origin!==EMBED_ORIGIN||e.source!==embed.frame.contentWindow) return;
    var m=null;
    try{ m=(typeof e.data==='string'?JSON.parse(e.data):e.data||{})['twttr.embed']; }catch(x){ return; }
    if(!m||typeof m.method!=='string') return;
    var p=(Array.isArray(m.params)&&m.params[0])||{};
    if(m.method==='twttr.private.resize'){
      var h=Number(p.height);
      if(isFinite(h)&&h>0){ embed.frame.style.height=Math.min(Math.ceil(h), 4000)+'px'; embed.drew(); }
    }
    else if(m.method==='twttr.private.rendered') embed.drew();
    else if(m.method==='twttr.private.no_results') embed.gone();
  });
  function dialog(){
    if(dlg) return dlg;
    dlg=document.createElement('dialog');
    dlg.className='tw-dlg tw';
    dlg.setAttribute('aria-label','Post from X');
    dlg.innerHTML='<div class="tw-dlg-head"><b class="tw-dlg-t"></b>'
      +'<button type="button" class="tw-dlg-x" aria-label="Close">&times;</button></div>'
      +'<div class="tw-dlg-body"></div>'
      +'<p class="tw-dlg-foot"><a class="tw-dlg-go" target="_blank" rel="noopener noreferrer">Open on X</a></p>';
    dlg.querySelector('.tw-dlg-x').addEventListener('click',function(){ shut(); });
    // A tap on the dimmed backdrop lands on the dialog element itself.
    dlg.addEventListener('click',function(ev){ if(ev.target===dlg) shut(); });
    // Closing empties it: a video left in a closed dialog keeps playing. The
    // event is queued, so a post opened since must not be emptied by it.
    dlg.addEventListener('close',function(){
      if(dlg.open) return;
      seq++; embed=null;
      dlg.querySelector('.tw-dlg-body').innerHTML='';
    });
    document.body.appendChild(dlg);
    return dlg;
  }
  function shut(){
    seq++; embed=null;
    dlg.querySelector('.tw-dlg-body').innerHTML='';
    if(typeof dlg.close==='function'&&dlg.open) dlg.close();
    else dlg.removeAttribute('open');
  }
  function show(c){
    var t=c&&state.byId[c.getAttribute('data-id')];
    if(!t) return;
    var d=dialog(), body=d.querySelector('.tw-dlg-body'), mine=++seq;
    d.querySelector('.tw-dlg-t').textContent=t.author||(t.handle?'@'+t.handle:'Post on X');
    d.querySelector('.tw-dlg-go').href=xUrl(t);
    body.innerHTML='<p class="tw-dlg-wait">Loading the post from X\\u2026</p>';
    if(typeof d.showModal==='function'){ if(!d.open) d.showModal(); }
    else d.setAttribute('open','');
    function fail(text){
      if(mine!==seq) return;
      embed=null;
      body.innerHTML='<p class="tw-dlg-wait">'+esc(text)+'</p>';
    }
    var dark=!!(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches);
    var f=document.createElement('iframe');
    f.className='tw-embed';
    f.title='Post from X';
    f.setAttribute('sandbox', CFG.sandbox);
    f.setAttribute('scrolling','no');
    // Only checked parts: the id passed ID above, the theme is one of two words.
    f.src=CFG.embed+'?id='+encodeURIComponent(t.tweet_id)+'&dnt=true&lang=en&theme='+(dark?'dark':'light');
    var timer=setTimeout(function(){ fail(CFG.blocked); }, CFG.wait);
    embed={frame:f,
      drew:function(){
        clearTimeout(timer);
        var w=body.querySelector('.tw-dlg-wait'); if(w) w.parentNode.removeChild(w);
      },
      gone:function(){ clearTimeout(timer); fail(CFG.gone); }};
    body.appendChild(f);
  }

  boxes.forEach(function(b){
    b.addEventListener('click',function(ev){
      var el=ev.target;
      if(!el.closest) return;
      var v=el.closest('.tw-vote');
      if(v){ ev.preventDefault(); vote(b, v); return; }
      var s=el.closest('.tw-show');
      if(s){ ev.preventDefault(); show(s.closest('.tw-card')); return; }
      var nav=el.closest('.tw-nav');
      if(nav){
        var row=b.querySelector('.tw-row');
        if(row) row.scrollBy({left:(+nav.getAttribute('data-dir')||1)*row.clientWidth*0.9, behavior:'smooth'});
        return;
      }
      if(el.closest('a,button,input,select,textarea,label,form')) return;
      // A tap on the card is "show me"; selecting its words is not.
      var sel=window.getSelection&&String(window.getSelection());
      var c=el.closest('.tw-card[data-id]');
      if(c&&!sel) show(c);
    });
    var open=b.querySelector('.tw-open'), form=b.querySelector('.tw-form');
    open.addEventListener('click',function(){
      form.hidden=!form.hidden;
      open.setAttribute('aria-expanded', String(!form.hidden));
      if(!form.hidden) form.querySelector('.tw-url').focus();
    });
    form.addEventListener('submit',function(ev){ ev.preventDefault(); send(b); });
  });

  function load(){
    return fetch(CFG.api,{credentials:'same-origin'})
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .then(draw, function(e){ console.warn('tweets: no list', e); failed(); })
      // Anything thrown while drawing is a bug, and says so.
      .catch(function(e){ console.error('tweets:', e); failed(); });
  }
  paintSubmit();
  load();

  window.GSTweets={draw:draw, show:show, state:state};
})();
</script>"""


def _ghosts(n: int) -> str:
    return "".join('<div class="tw-card tw-ghost" aria-hidden="true"></div>' for _ in range(n))


def _submit(uid: str) -> str:
    """The submit control and its form. Signed out it is a link to sign in;
    signed in, a button that opens the form - one 40px line either way."""
    return (
        '<div class="tw-foot">'
        '<a class="tw-sub tw-signin" href="/api/auth/login">Sign in to submit</a>'
        '<button type="button" class="tw-sub tw-open" aria-expanded="false" '
        f'aria-controls="tw-form-{uid}" hidden>Submit a post</button>'
        f'<p class="tw-say" role="status">{escape(CONFIG["say"])}</p></div>'
        f'<form class="tw-form" id="tw-form-{uid}" hidden novalidate>'
        f'<label for="tw-url-{uid}">Link to a funny college football or NFL post on X</label>'
        '<div class="tw-fields">'
        f'<input id="tw-url-{uid}" class="tw-url" type="url" inputmode="url" autocomplete="off" '
        'autocapitalize="off" spellcheck="false" maxlength="500" '
        'placeholder="https://x.com/&hellip;/status/&hellip;">'
        '<select class="tw-sport" aria-label="Which sport">'
        '<option value="">Sport?</option><option value="cfb">College</option>'
        '<option value="nfl">NFL</option></select>'
        '<button type="submit" class="tw-send">Send</button></div>'
        '<p class="tw-said" role="status"></p></form>')


def _script() -> str:
    return JS.replace("__CFG__", script_json(CONFIG))


def home_card() -> str:
    """Home's "Tweets of the week": a swipeable row of the week's posts."""
    return ("{% raw %}" + CSS
            + f'<section class="home-card tw tw-home" data-tw="row" data-max="{HOME_MAX}">'
            '<div class="home-card-head"><h2>Tweets of the week</h2><span class="tw-head-r">'
            '<button type="button" class="tw-nav" data-dir="-1" aria-label="Back">&lsaquo;</button>'
            '<button type="button" class="tw-nav" data-dir="1" aria-label="More">&rsaquo;</button>'
            '<a class="home-card-link" href="/tweets/">All posts &rarr;</a></span></div>'
            f'<div class="tw-list tw-row" aria-busy="true">{_ghosts(3)}</div>'
            + _submit("home") + "</section>" + _script() + "{% endraw %}")


def body() -> str:
    """/tweets/: the whole week in a grid, the submit box above it."""
    return (CSS + f'<div class="tw tw-page" data-tw="grid" data-max="{PAGE_MAX}">'
            f'<p class="tw-intro">{escape(HOW)} Tap a card to see the post itself.</p>'
            + _submit("page")
            + f'<div class="tw-list tw-grid" aria-busy="true">{_ghosts(3)}</div></div>'
            + _script())


def generate() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(add_front_matter(
        body(), "Tweets of the week", "The funniest college football and NFL posts on X, "
        "picked from what readers send in", updated=False,
        description="The funniest college football and NFL posts on X this week, sent in by "
                    "GordStats readers and voted up by them."),
        encoding="utf-8")
    print(f"Wrote tweets of the week -> {OUT}")


if __name__ == "__main__":
    generate()
