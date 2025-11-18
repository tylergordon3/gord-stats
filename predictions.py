import utils
from sklearn import preprocessing
from pretty_html_table import build_table

def predict(date):
    randomForest = utils.read_from_pickle('forest')
    decisionTree = utils.read_from_pickle('dt')
    supportVC = utils.read_from_pickle('svc')
    
    [kenpom_path, torvik_path] = utils.get_recent_data()
    kenpom_data = utils.load_json_data(kenpom_path)
    torvik_data = utils.load_json_data(torvik_path)

    teams = torvik_data['Team']
   
    cbb_now = torvik_data.drop(columns=['Barthag', 'WAB','Team', 'Conf', 'Rec', 'G', 'Rk', 'FTR', '3PR', '3PRD'])
    scaler = preprocessing.StandardScaler()
    x_predict = scaler.fit_transform(cbb_now)
    forest_predict = randomForest.predict(x_predict)
    torvik_data['POSTSEASON'] = forest_predict
    df = torvik_data
    #df = torvik_data.drop(columns=['ADJOE', 'ADJDE', 'BARTHAG', 'EFG_O', 'EFG_D', 'TOR', 'TORD',
        #'ORB', 'DRB', 'FTR', 'FTRD', '2P_O', '2P_D', '3P_O', '3P_D', 'ADJ_T', 'WAB'])
    def strip(team):
        for i, char in enumerate(team):
            if char == '(':
                return team[:i]
            if team[i:i+3] == 'vs.':
                return team[:i]
        return team
    march_madness = df[df["POSTSEASON"] == True].copy()
    march_madness['Team'] = march_madness['Team'].apply(lambda x: strip(x))
    march_madness = march_madness.drop(columns=['POSTSEASON'])
    html_table_blue_light = build_table(march_madness.head(64), 'green_dark')
    html = '<a href="index.html" title="Home">Home</a>'
    html += f'<p>Prediction for {date}</p>'
    html += html_table_blue_light
    # Save to html file
    with open(f'docs/predict_{date}.html', 'w') as f: 
        f.write(html)  
