What we're trying to do:

We're looking to build a localy run MCP (in Python, managed by `uv`) to be setup and used in project folders that are setup to work with Claude and Claude code to work with a specific Superhuamn Docs Document. 

In a specific project folder, a .env will be setup to pass API keys along with the calls to give access to the Superhuman Doc API. 


Reference lock is : https://docs.superhuman.com/developers/apis/v1
    - https://coda.io/apis/v1/openapi.yaml

(we should log what version we're building against, so upgrades are easy and tracked)