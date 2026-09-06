## Trace
Trace is AI agent that scans your vibecoded apps for secuity vulnerabilities and pre-launch mistakes that could cost you or your users when you hit production. The agentic era has given anyone the ability to build an entire application without needing technical or product expertise.
But to launch an app on any platform, there are technical, product and legal decisions to be made to prevent you or your users from being compromised. Trace exposed those gaps present in your app that need your attention before launching to the market.
Trace is built for the non-technical builders who lack the technical and product expertise for successfully launching in application on a production environment.

## System Architecture
On a high level, Trace will operate with the client-server model, with the server layer being a combination of a relational database, API server and a cache (for saving frequently accessed data). 

## Tech Stack 
- React: The library of choice for building the user interface for Trace, with the Typescript programming language. React was chosen because it the most popular library for building user-interfaces with huge community support.
- Fast API: The library of choice for building the API server, with the Python programming language. FastAPI makes it easy and flexible to build APIs in Python.
- PostgreSQL: The relational database of choice for storing data.
- Redis: The cache client for saving frequently-accessed data to improve API server performance.
- Langchain/Langgraph: For building and orchestrating AI agents and coordinating AI workflows.
- Langsmith: For adding observabilty to AI agent and workflow runs to ensure relaiblity of results and findings.
- Sentry: For error monitoring and obserability of API serve and user interface to ensure reliability of the platform.
