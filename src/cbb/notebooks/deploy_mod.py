import subprocess
import sys

# Call main
result = subprocess.run([sys.executable, "src/cbb/main.py"])

# Clean last build
result = subprocess.run(
    ['bundle', 'exec', 'jekyll', 'clean', "--source docs", 
     "--destination docs/_site"],
    capture_output=True,
    text=True
)

# Build new build
result = subprocess.run(
    ['bundle', 'exec', 'jekyll', 'build', "--source docs", 
     "--destination docs/_site"],
    capture_output=True,
    text=True
)

# Deploy
result = subprocess.run(
    ['npx', 'wrangler', 'pages', 'deploy', "docs/_site", 
     "--project-name=gordstats-cbb", "--commit-dirty=true"],
    capture_output=True,
    text=True
)