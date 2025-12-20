from bs4 import BeautifulSoup
import utils
import html_builder as htmb

def render_home(men_rankings, men_games_html, women_rankings, women_games_html):
    """
    Creates index.html for home page of our website
    
    :param men_rankings: Men's DataFrame of current model rankings 
    :type men_rankings: DataFrame
    :param men_games: Today's slate of games and scores for men
    :type men_games: String of HTML
    :param women_rankings: Women's DataFrame of current model rankings 
    :type women_rankings: DataFrame
    :param women_games: Today's slate of games and scores for women
    :type women_games: String of HTML
    """

    men_soup = BeautifulSoup(men_games_html, "html.parser")
    women_soup = BeautifulSoup(women_games_html, "html.parser")

    def getPower5(soup):
        h3 = soup.find('h3')
        content = []
        for elem in h3.next_siblings:
            if elem.name == "h3":
                break
            content.append(str(elem))
        result = "".join(content)
        return result
    
    men_games = getPower5(men_soup)
    women_games = getPower5(women_soup)

    html = "<h3>Men's Power 5 Games Today</h3>" + men_games + "<h3>Women's P5 Games Today</h3>" + women_games
    path =  utils.get_path('docs/index.html')
    html = htmb.add_front_matter(html, "GordStats Home")

    with open(path, "w") as f:
        f.write(html)
        print(f"Wrote to: {path}")