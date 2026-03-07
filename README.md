# Helsinki Event Aggregator (High-Performance AWS Lambda API)

This project is a **serverless API Orchestrator** that aggregates, normalizes, and serves event data from major Helsinki sources in real-time. By utilizing a **hybrid multi-threaded and asynchronous architecture**, it processes hundreds of data points from MyHelsinki, Luma, and LinkedEvents in seconds.

---

## Technical Highlights

- **Hybrid Concurrency:** Combines `ThreadPoolExecutor` for standard REST APIs with `asyncio` and `aiohttp` for complex, nested data fetching.
- **Performance Optimization:** Reduced execution time for LinkedEvents from 60+ seconds to under 5 seconds by implementing parallel request pooling and URL de-duplication.
- **Data Normalization:** Maps inconsistent schemas from three different providers into a single, clean JSON format for frontend consumption.
- **DevOps Pipeline:** Fully automated CI/CD using GitHub Actions, handling environment builds, dependency zipping, and AWS Lambda deployment.

---

## Tech Stack

- **Runtime:** Python 3.9
- **Core Libraries:** `aiohttp`, `asyncio`, `requests`, `concurrent.futures`
- **Infrastructure:** AWS Lambda, IAM, API Gateway
- **CI/CD:** GitHub Actions

---

## Architecture Overview

The Lambda function acts as a central hub. When a request hits the API Gateway, the function:

1. Identifies the requested sources via query parameters.
2. Triggers parallel workers to scrape external APIs.
3. Performs an **Async Burst** for LinkedEvents to fetch deep-linked location and keyword data.
4. Returns a unified, sorted list of events.

```mermaid
graph TD
    A[GET /events?source=all<br/>API Gateway] --> B[AWS Lambda Function]
    B --> C{Parallel Workers<br/>ThreadPoolExecutor}

    C --> D[MyHelsinki API<br/>requests]
    C --> E[Luma API<br/>requests]
    C --> F[LinkedEvents API<br/>aiohttp + asyncio]

    F --> F2{Async Burst<br/>Nested Data}
    F2 --> F3[Fetch Locations]
    F2 --> F4[Fetch Keywords]
    F3 & F4 --> F5[URL De-duplication]

    D & E & F5 --> G[Data Normalization & Cleaning]
    G --> H[Unified JSON Response<br/>Sorted by date]

    style A fill:#4CAF50,stroke:#333,stroke-width:2px,color:#fff
    style B fill:#FF9800,stroke:#333,stroke-width:2px,color:#fff
    style C fill:#FFC107,stroke:#333,stroke-width:2px,color:#000
    style D fill:#2196F3,stroke:#333,stroke-width:2px,color:#fff
    style E fill:#2196F3,stroke:#333,stroke-width:2px,color:#fff
    style F fill:#2196F3,stroke:#333,stroke-width:2px,color:#fff
    style F2 fill:#00BCD4,stroke:#333,stroke-width:2px,color:#fff
    style F3 fill:#00ACC1,stroke:#333,stroke-width:2px,color:#fff
    style F4 fill:#00ACC1,stroke:#333,stroke-width:2px,color:#fff
    style F5 fill:#26C6DA,stroke:#333,stroke-width:2px,color:#fff
    style G fill:#9C27B0,stroke:#333,stroke-width:2px,color:#fff
    style H fill:#607D8B,stroke:#333,stroke-width:2px,color:#fff

    linkStyle 0 stroke:#4CAF50,stroke-width:2px
    linkStyle 1 stroke:#FF9800,stroke-width:2px
    linkStyle 2 stroke:#FFC107,stroke-width:2px,stroke-dasharray: 5,5
    linkStyle 3 stroke:#FFC107,stroke-width:2px,stroke-dasharray: 5,5
    linkStyle 4 stroke:#FFC107,stroke-width:2px,stroke-dasharray: 5,5
    linkStyle 5 stroke:#00BCD4,stroke-width:2px
    linkStyle 6 stroke:#00BCD4,stroke-width:2px,stroke-dasharray: 5,5
    linkStyle 7 stroke:#00BCD4,stroke-width:2px,stroke-dasharray: 5,5
    linkStyle 8 stroke:#26C6DA,stroke-width:2px
    linkStyle 9 stroke:#26C6DA,stroke-width:2px
    linkStyle 10 stroke:#9C27B0,stroke-width:2px
    linkStyle 11 stroke:#9C27B0,stroke-width:2px
    linkStyle 12 stroke:#9C27B0,stroke-width:2px
    linkStyle 13 stroke:#607D8B,stroke-width:2px
```

---

## API Usage

**Endpoint:** `GET /events?source=all`

| Parameter | Values | Description |
|:----------|:-------|:------------|
| `source`  | `myhelsinki`, `luma`, `linked_events`, `all` | Filter by event source. Defaults to `all`. |

**Response Schema:**

```json
{
  "events": [
    {
      "id": "string",
      "title": "string",
      "description": "string",
      "start_time": "ISO 8601",
      "end_time": "ISO 8601",
      "location": "string",
      "url": "string",
      "source": "myhelsinki | luma | linkedevents"
    }
  ]
}
```

---

## Setup & Deployment

### 1. Clone & Initialize

```bash
git clone https://github.com/A2p3kt/helsinki-event-aggregator.git
cd helsinki-event-aggregator
python -m venv venv
source venv/bin/activate   # On macOS/Linux
venv\Scripts\activate      # On Windows
pip install -r requirements.txt
```

### 2. Run Locally

You can test the handler logic directly before deploying to the cloud.

```python
# example local test
from lambda_function import lambda_handler
result = lambda_handler({"source": "all"}, None)
print(result)
```

### 3. CI/CD Secrets

To enable automated deployment, add the following to your **GitHub Repository Secrets**:

> [!IMPORTANT]
>
> `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION` must all be set before the pipeline can deploy successfully.

---

## CI/CD Pipeline

The deployment process is fully automated via GitHub Actions. The `.github/workflows/deploy.yml` workflow handles:

```mermaid
graph LR
    A[Push to main] --> B[GitHub Actions Triggered]
    B --> C[Install Dependencies<br/>from requirements.txt]
    C --> D[Package into<br/>Deployment ZIP]
    D --> E[Deploy to AWS Lambda<br/>via GitHub Secrets]
    E --> F[Live Function Updated]

    style A fill:#4CAF50,stroke:#333,stroke-width:2px,color:#fff
    style B fill:#24292e,stroke:#333,stroke-width:2px,color:#fff
    style C fill:#2196F3,stroke:#333,stroke-width:2px,color:#fff
    style D fill:#FF9800,stroke:#333,stroke-width:2px,color:#fff
    style E fill:#FFC107,stroke:#333,stroke-width:2px,color:#000
    style F fill:#607D8B,stroke:#333,stroke-width:2px,color:#fff

    linkStyle 0 stroke:#4CAF50,stroke-width:2px
    linkStyle 1 stroke:#24292e,stroke-width:2px
    linkStyle 2 stroke:#2196F3,stroke-width:2px
    linkStyle 3 stroke:#FF9800,stroke-width:2px
    linkStyle 4 stroke:#FFC107,stroke-width:2px
```

| Step | Description |
| :----- | :------------ |
| **Dependency Management** | Installs libraries from `requirements.txt` into the build environment |
| **Packaging** | Creates a deployment ZIP file compatible with the AWS Lambda runtime |
| **Deployment** | Updates the Lambda function code using credentials stored in GitHub Secrets |
