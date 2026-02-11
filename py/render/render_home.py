from bs4 import BeautifulSoup
import utils
import html_util

def render_home():
    # Use a raw string (r''') to handle any special characters safely
    html = r'''
    {% include countdown.html %} 
    <div class="home-grid">
      <div class="home-left">
        <h1>GordStats Home</h1>
        <p>Using machine learning to predict the NCAA March Madness field.</p>
        <p>
          Data Sources:
          <a href="https://kenpom.com/">Kenpom</a> |
          <a href="https://barttorvik.com/#">Torvik</a>
        </p>
        <p>
          Today's scores and schedule from:
          <a href="https://www.cbssports.com/college-basketball/scoreboard/">CBS Sports</a>
        </p>
        <p>See the scores tab for men's scoreboard.</p>
      </div>

      <div class="home-right">
        <div class="twitter-title">Live Updates</div>
        <a class="twitter-timeline"
           data-theme="dark"
           data-height="520"
           href="https://twitter.com/JonRothstein?ref_src=twsrc%5Etfw">
           Tweets by JonRothstein
        </a>
      </div>
    </div>
    
   <script>
  // This tells X to scan the page for the "twitter-timeline" link again
  window.twttr = (function(d, s, id) {
    var js, fjs = d.getElementsByTagName(s)[0], t = window.twttr || {};
    if (d.getElementById(id)) return t;
    js = d.createElement(s); js.id = id;
    js.src = "https://platform.twitter.com/widgets.js";
    fjs.parentNode.insertBefore(js, fjs);
    t._e = []; t.ready = function(f) { t._e.push(f); };
    return t;
  }(document, "script", "twitter-wjs"));
</script>
    '''
    # Note: Removed the redundant "html += ..." line as it's already in the block above.
    
    path = utils.get_path('docs/index.html')
    html = html_util.add_front_matter(html, "GordStats Home")

    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path}")