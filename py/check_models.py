import utils
import model
import json
import constants
import pandas as pd
import kenpom_model
from sklearn.metrics import classification_report 

torvik_dataset_path = utils.get_path("model_data/cbb_data.json")
kenpom_dataset_path = utils.get_path("model_data/kenpom_all.json")

torvik_df = utils.load_json_data(torvik_dataset_path)
with open('model_data/kenpom_all.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
kenpom_df = pd.DataFrame(data, columns=constants.kenpom)

[cbb, ind, _] = model.chiSquared(torvik_df)
[X_train, X_test, y_train, y_test, _] = model.splitData(cbb, ind)

randomForest = utils.read_from_pickle('forest')
decisionTree = utils.read_from_pickle('dt')
supportVC = utils.read_from_pickle('svc')
    
rf_predict = randomForest.predict(X_test)
print(classification_report(y_test, randomForest.predict(X_test))) 
print("test score random forest torvik : {}\n".format(randomForest.score(X_test, y_test)))

dt_predict = decisionTree.predict(X_test)
print(classification_report(y_test, decisionTree.predict(X_test))) 
print("test score decision tree torvik : {}\n".format(decisionTree.score(X_test, y_test)))

svc_predict = supportVC.predict(X_test)
print(classification_report(y_test, supportVC.predict(X_test))) 
print("test score support vc torvik : {}\n".format(supportVC.score(X_test, y_test)))

[cbb, ind] = kenpom_model.chiSquared(kenpom_df)
[kX_train,kX_test, ky_train, ky_test] = kenpom_model.splitData(cbb, ind)

randomForest_kenpom = utils.read_from_pickle('kp_forest')
decisionTree_kenpom = utils.read_from_pickle('kp_dt')
supportVC_kenpom = utils.read_from_pickle('kp_svc')

    
rf_predict_k = randomForest_kenpom.predict(kX_test)
print(classification_report(ky_test, randomForest_kenpom.predict(kX_test))) 
print("test score random forest kenpom : {}\n".format(randomForest_kenpom.score(kX_test, ky_test)))

dt_predict_k = decisionTree_kenpom.predict(kX_test)
print(classification_report(ky_test, decisionTree_kenpom.predict(kX_test))) 
print("test score decision tree torvik : {}\n".format(decisionTree_kenpom.score(kX_test, ky_test)))

svc_predict_k = supportVC_kenpom.predict(kX_test)
print(classification_report(ky_test, supportVC_kenpom.predict(kX_test))) 
print("test score support vc torvik : {}\n".format(supportVC_kenpom.score(kX_test, ky_test)))
