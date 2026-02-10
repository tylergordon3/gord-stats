from bs4 import BeautifulSoup
import utils
import html_builder as htmb

def render_home():
    html = '''
    {% include countdown.html %} 
    <p>Using machine learning to predict the NCAA March Madness field.</p>
    <p>Data Sources: <a href='https://kenpom.com/'>Kenpom</a> | <a href='https://barttorvik.com/#'>Torvik</a></p>
    <p>Today's scores and schedule from: <a href='https://www.cbssports.com/college-basketball/scoreboard/'>CBS Sports</a></p>
'''
    html += "See the scores tab for men's scoreboard."
    path =  utils.get_path('docs/index.html')
    html = htmb.add_front_matter(html, "GordStats Home")

    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path}")