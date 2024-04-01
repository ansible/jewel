# Service test app

This is a python app that implements Organizations, Teams and Users via the resources API for testing purpose. It uses an in memory sqlite database, and is designed to be launched via fixtures for testing communications between the gateway and various services.

This app implements JWT authentication and the resources API from DAB and can spoof Controller, Hub and EDA.
