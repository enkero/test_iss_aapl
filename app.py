import pandas as pd
import numpy as np
import datetime
import warnings
warnings.simplefilter('ignore')
from dateutil.relativedelta import relativedelta
import requests
import ast
import math
from scipy.stats import spearmanr
from flask import Flask, jsonify, abort, make_response, request
from config import *


###   Find 5 last trading weekdays   ###

today = datetime.datetime.now()
lastweek = pd.date_range(start = today.date() - datetime.timedelta(days=7), end = today.date() - datetime.timedelta(days=1))
dayofweek_lastweek = pd.Series(lastweek).dt.dayofweek
weekdays = lastweek[dayofweek_lastweek.isin([0,1,2,3,4])]


###   Download AAPL data for those dates   ###

start_timestamp = int((weekdays[0] + datetime.timedelta(hours = nasdaq_time)).timestamp())
end_timestamp = int((weekdays[-1] + datetime.timedelta(days=1) + datetime.timedelta(hours = nasdaq_time)).timestamp())

aapl = requests.get('https://eodhistoricaldata.com/api/intraday/AAPL.US?api_token=demo&interval=1m&from=' + str(start_timestamp) + '&to=' + str(end_timestamp)).content

aapl = [x.split(',') for x in aapl.decode().split('\n')]
aapl = pd.DataFrame(aapl[1:], columns=aapl[0])

del aapl['Gmtoffset']
aapl = aapl[aapl['Timestamp']!='']
aapl.loc[aapl['Volume']=='', 'Volume'] = 0

for col in ['Timestamp', 'Volume']:
    aapl[col] = aapl[col].astype(int)
for col in ['Open', 'High', 'Low', 'Close']:
    aapl[col] = aapl[col].astype(float)   
    
aapl['Datetime'] = [x.replace('"', '') for x in aapl['Datetime']]
aapl['Datetime'] = pd.to_datetime(aapl['Datetime'])

aapl['Date'] = [str(x).split('T')[0] for x in aapl['Datetime'].values]
aapl = aapl[aapl['Date'].isin(weekdays.astype(str))]

aapl.to_csv(filename_aapl, index=False)


###   Download ISS location data for those dates   ###

iss = []

for i in range(math.ceil(aapl.shape[0]/batch_size)):
    list_timestamps = ','.join(aapl['Timestamp'].astype(str).values[i*batch_size:(i+1)*batch_size])
    batch = requests.get('https://api.wheretheiss.at/v1/satellites/25544/positions?timestamps=' + list_timestamps).content
    iss += ast.literal_eval(batch.decode())
    
iss = pd.DataFrame(iss)
iss = iss[['latitude', 'longitude', 'altitude', 'timestamp']]    

iss.to_csv(filename_iss, index=False)


###   Let's add cartesian coordinates and check them also   ###
#x = R * cos(lat) * cos(lon)
#y = R * cos(lat) * sin(lon)
#z = R * sin(lat)

iss['x_coord'] = (R+iss['altitude']) * np.cos(iss['latitude'] * math.pi/180) * np.cos(iss['longitude'] * math.pi/180)
iss['y_coord'] = (R+iss['altitude']) * np.cos(iss['latitude'] * math.pi/180) * np.sin(iss['longitude'] * math.pi/180)
iss['z_coord'] = (R+iss['altitude']) * np.sin(iss['latitude'] * math.pi/180)


###   Compute the Spearman correlation coefficient which suits here most, and the p-value to get some measure of the reliability of these results    ###

aapl = pd.merge(aapl, iss, left_on='Timestamp', right_on='timestamp', how='left')
del iss

corr = []
for var in ['latitude', 'longitude', 'altitude', 'x_coord', 'y_coord', 'z_coord']:
    corr += [spearmanr(aapl['Open'], aapl[var], nan_policy='omit')]
    
corr = pd.DataFrame(corr)
corr['variable'] = ['latitude', 'longitude', 'altitude', 'x_coord', 'y_coord', 'z_coord']   

corr.to_csv(filename_correlation, index=False)


####    API itself    ####  

app = Flask(__name__)

@app.errorhandler(400)
def error400(error):
    return jsonify({'success': False, 'error': 400, 'message': error.description})


@app.errorhandler(404)
def error404(error):
    return jsonify({'success': False, 'error': 404, 'message': error.description})


@app.errorhandler(500)
def error500(error):
    return jsonify({'success': False, 'error': 500, 'message': 'Internal Server Error'})
    

# http://0.0.0.0:5000/corr/api/iss
@app.route('/corr/api/iss', methods=['GET'])
def get_predictions():
    
    #args=request.args.to_dict()
       
    return jsonify({"success": True, "variable": ','.join(corr['variable']),
                    "correlation": ','.join(map(str, corr['correlation'])), "pvalue": ','.join(map(str, corr['pvalue']))})

if __name__ == '__main__':
    app.run(debug=True)
    
    