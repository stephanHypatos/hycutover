# Project Copy and Compare Streamlit App

## Overview
This is a Streamlit-based web application that provides functionalities for comparing schemas at a detailed level and copying projects within one or between two companies using API authentication. The app consists of two main functionalities:

1. **Schema Comparison**
   - Authenticates source and target company credentials.
   - Fetches and compares schemas between selected projects.
   - Displays differences in data points and meta-level attributes.

2. **Project Copying**
   - Copies projects from a source company to a target company.
   - Allows specifying a new extraction model ID.
   - Supports cloning routing rules of projects.

## Features
- Secure API authentication using `HypatosAPI`.
- Schema comparison at data point and meta levels using `DeepDiff`.
- Copy projects with custom parameters.
- Fetch and copy routing rules.
- Retrieve extraction model ID from target projects.

## Technologies Used
- **Python**
- **Streamlit**
- **Pandas**
- **DeepDiff**
- **Requests**

## Installation
### Prerequisites
Ensure you have Python installed (>= 3.11).

### Steps to Install
1. Clone the repository:
   ```sh
   git clone https://github.com/stephanHypatos/hycutover
   cd your-repo
   ```
2. Install the required dependencies:
   ```sh
   pip install -r requirements.txt
   ```
3. Run the Streamlit app:
   ```sh
   streamlit run app.py
   ```

## Usage
### Authentication
- Enter the source and target company credentials.
- Click "Authenticate Credentials" to verify.

### Schema Comparison
1. Navigate to "Compare Datapoints" or "Compare Metadata".
2. Select the source project.
3. Select one or multiple target projects.
4. Click "Compare" to see the differences.

### Project Copying
1. Navigate to "Copy Projects".
2. Select projects to copy.
3. Enter a new extraction model ID.
4. Click "Create Project Copies".

### Copy Routing Rules
1. Navigate to "Copy Routing Rules".
2. Click "Copy Routing Rules" to transfer routing rules between projects.

### Get Model ID
1. Navigate to "Get Model ID".
2. Select a project to retrieve its extraction model ID.

## Configuration
Modify `config.py` to set the `BASE_URL` for API requests.

## License
This project is licensed under the MIT License - see the LICENSE file for details.

## Contact
For any issues or feature requests, open an issue on the GitHub repository.

