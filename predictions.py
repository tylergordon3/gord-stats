import utils

def predict():
    randomForest = utils.read_from_pickle('forest')
    decisionTree = utils.read_from_pickle('dt')
    supportVC = utils.read_from_pickle('svc')
    
    [kenpom_path, torvik_path] = utils.get_recent_data()
    kenpom_data = utils.load_json_data(kenpom_path)
    torvik_data = utils.load_json_data(torvik_path)
