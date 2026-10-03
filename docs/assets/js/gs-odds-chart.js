/* Playoff and title odds over the season: picks out the reader's team.
   Source file, loaded by gordstats.odds_chart (JS_TAG); see gordstats.js_assets.

   The chart arrives drawn, with the site owner's team picked out. This picks
   out the reader's instead - the team their team dashboard remembers
   (data-store: nflMyTeam / cfbMyTeam) - and follows the Team menu, or a tap
   on a line, after.
   Only colours and the dots move: the plot box keeps its size. */
(function(){
  function each(list, fn){ Array.prototype.forEach.call(list, fn); }

  function pick(box, key){
    var found=false;
    each(box.querySelectorAll('.oc-plot'), function(plot){
      var svg=plot.querySelector('svg'), line=null;
      each(svg.querySelectorAll('.oc-ln'), function(l){
        var on=l.getAttribute('data-k')===key;
        l.classList.toggle('oc-on', on);
        if(on) line=l;
      });
      each(plot.querySelectorAll('.oc-dot,.oc-end'), function(e){ e.parentNode.removeChild(e); });
      if(!line) return;
      found=true;
      svg.insertBefore(line, svg.querySelector('.oc-hits'));   // last line drawn: on top
      var pts=line.getAttribute('points').trim().split(/\s+/);
      var live=box.hasAttribute('data-live');
      pts.forEach(function(p, i){
        var xy=p.split(','), d=document.createElement('span');
        d.className='oc-dot'+(live&&i===pts.length-1?' oc-live':'');
        d.style.left=xy[0]+'%'; d.style.top=xy[1]+'%';
        plot.appendChild(d);
      });
      var end=document.createElement('span');
      end.className='oc-end';
      end.style.top=pts[pts.length-1].split(',')[1]+'%';
      end.textContent=line.getAttribute('data-end')||'';
      plot.appendChild(end);
    });
    each(box.querySelectorAll('tr[data-k]'), function(tr){
      tr.classList.toggle('oc-on', tr.getAttribute('data-k')===key);
    });
    var sel=box.querySelector('.oc-pick select');
    if(sel) sel.value=key;
    box.setAttribute('data-on', key);
    return found;
  }

  each(document.querySelectorAll('.oc[data-on]'), function(box){
    var sel=box.querySelector('.oc-pick select');
    var store=box.getAttribute('data-store'), mine=null;
    try{ if(store) mine=localStorage.getItem(store); }catch(e){}
    var has=mine && Array.prototype.some.call(box.querySelectorAll('.oc-ln'), function(l){
      return l.getAttribute('data-k')===mine; });
    if(has && mine!==box.getAttribute('data-on')) pick(box, mine);
    if(sel) sel.addEventListener('change', function(){ pick(box, sel.value); });
    // A tap on a line picks it out too (each line has a wide invisible twin).
    box.addEventListener('click', function(ev){
      var hit=ev.target.closest&&ev.target.closest('.oc-hit');
      if(hit) pick(box, hit.getAttribute('data-k'));
    });
  });
})();
