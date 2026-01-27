'''
Docstring for py.kenpom
Documentation:
    https://kenpom.com/api-documentation.php
'''
import kenpom_wrapper
from dotenv import load_dotenv

load_dotenv() 

kenpom = kenpom_wrapper.KenpomData()
print(kenpom.get_ratings(2025))