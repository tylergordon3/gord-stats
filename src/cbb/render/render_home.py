from cbb import html_util
from cbb.lib import paths


def render_home():
    # Raw string to preserve formatting
    html = r"""
    {% include countdown.html %} 
    <div class="home-grid">
      <div class="home-left">
        <p>Using machine learning to predict the NCAA March Madness field.</p>
        <p>
          Data Sources:
          <a href="https://kenpom.com/">Kenpom</a> |
          <a href="https://barttorvik.com/#">Torvik</a>
        </p>
        <p>
          Today's scores and schedule from:
          <a href="https://www.thescore.com/">TheScore</a>
        </p>
      </div>

      <div class="home-right">
        <blockquote class="twitter-tweet">
          <p lang="en" dir="ltr">This is March.</p>&mdash; Jon Rothstein (@JonRothstein)
          <a href="https://twitter.com/JonRothstein/status/1498523424167243778?ref_src=twsrc%5Etfw">
          March 1, 2022</a>
        </blockquote> 
        <script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
      </div>
    </div>

    <script>
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
    """

    path = paths.WEB_HOME
    path.parent.mkdir(parents=True, exist_ok=True)

    html = html_util.add_front_matter(html, "GordStats Home")

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
        print(f"Wrote to: {path}")