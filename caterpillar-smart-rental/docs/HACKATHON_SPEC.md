# Caterpillar Smart Rental Tracking System (SRTS)

> **Historical reference:** This preserves the original SRTS hackathon requirements and sample handout. Current FleetSignal setup and reliability behavior are documented in [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md), and [RELIABILITY.md](RELIABILITY.md).

## 1. Document Purpose

This document captures the Caterpillar hackathon problem statement, the requirements communicated by the organizers, the official sample data provided in the handout, and the expected capabilities of the solution.

This document is the authoritative product/problem specification for the hackathon.

It intentionally does not prescribe the implementation architecture, technology stack, database design, API structure, or specific AI/ML algorithms. Those decisions belong in `IMPLEMENTATION_PLAN.md`.

---

## 2. Background

In industries such as construction, mining, and infrastructure development, companies frequently rent Caterpillar machines from registered Caterpillar dealers rather than purchasing the equipment outright.

The operational problem is not simply renting the machines. It is managing and monitoring those rental assets after they have been rented.

Dealers may have limited visibility into:

- Where a rental asset currently is
- Which customer is using it
- Which site it is operating at
- Who is operating it
- Whether it is actually being used
- Whether it is being used effectively
- How much idle time it has
- Whether it is being operated safely
- When it is expected to return
- Whether it should be reallocated
- Whether its usage indicates a potential maintenance problem

This lack of visibility can result in:

- Lost or unaccounted-for equipment
- Asset misallocation
- Underutilized rental assets
- Excessive idle time
- Unexpected downtime
- Delayed asset recovery
- Rental extensions and additional costs
- Safety issues
- Inefficient fleet allocation

The organizers emphasized that a single misplaced asset can result in significant financial loss, potentially amounting to thousands of dollars per day in some rental/project contexts.

---

## 3. Core Challenge

Design a Smart Rental Tracking System that helps Caterpillar dealers:

1. Track and monitor rented equipment
2. Understand how equipment is being used
3. Identify underutilized or incorrectly allocated equipment
4. Detect anomalous or unsafe operating conditions
5. Track the complete rental lifecycle
6. Forecast future equipment demand
7. Recommend operational actions based on the available data

The system should turn equipment and rental data into actionable dealer decisions.

The central operational question is:

> Where is each asset, how is it being used, what is wrong with it, what is likely to happen next, and what should the dealer do?

---

## 4. Required Capabilities

The solution is expected to demonstrate the following capabilities.

### 4.1 Asset Dashboard

Provide a dashboard containing the rented equipment fleet.

The dashboard should provide visibility into relevant asset information such as:

- Equipment/asset ID
- Equipment type
- Current/live status
- Customer, where applicable
- Site
- Operator
- Location
- Rental status
- Usage/utilization
- Important alerts or anomalies

The dashboard should allow a dealer/operations manager to quickly identify assets that require attention.

The dashboard should support operational decision-making rather than simply displaying raw data.

---

### 4.2 Check-in / Check-out

Provide a simple and traceable check-in/check-out process.

The organizers suggested methods such as:

- QR code
- RFID
- Manual asset entry

Physical RFID hardware is not required for the hackathon.

The important requirement is traceability of the asset throughout its lifecycle.

The lifecycle should conceptually cover:

**Dealership → Checkout → Customer/Site → Operation → Return/Check-in → Dealership**

Relevant lifecycle events should be recorded so that the system can answer questions such as:

- When was the asset checked out?
- Where was it assigned?
- Who was operating it?
- When did it operate?
- When was it returned?
- What happened to the asset during the rental period?

---

### 4.3 Usage Logging

The system should capture or display available usage information including:

- Runtime / engine hours
- Fuel usage
- Location
- Idle hours
- Operating days
- Total rented hours
- Usage by site
- Usage trends
- Utilization

The organizers emphasized that data should be used to determine whether rented machines are being used effectively.

High idle time or very low productive runtime should be considered potential indicators of inefficient utilization.

Telemetry may be simulated for the hackathon.

---

### 4.4 Alerts and Notifications

The system should support an alerting/notification mechanism.

Possible notification mechanisms include:

- Email
- Push notification
- SMS
- In-application alerts

Actual external notification infrastructure is not required for the MVP unless it is simple to implement.

Alerts should cover situations such as:

- Rental/check-in approaching
- Rental overdue
- Contract expiry
- Unexpected rental extension
- Location mismatch
- Underutilization
- Missing site assignment
- Missing operator assignment
- Unsafe operation
- Abnormal telemetry
- Potential maintenance issues

Alerts should be actionable and preferably explain:

**What happened → Why it matters → What should be done**

---

### 4.5 Demand Forecasting

Use historical rental/usage information to forecast future equipment requirements.

The organizers gave the following example:

A site historically uses a large number of excavators. Based on historical demand, the system should be able to predict that the site may require additional excavators during a future period.

The forecasting capability should help a dealer answer:

- Which equipment type will be needed?
- At which site?
- When will it be needed?
- How many assets may be required?
- Which currently rented assets are expected to return?
- Which available/returning assets could be allocated to future demand?

Forecasting should ultimately support an operational decision such as asset pre-positioning or reallocation.

A simple, explainable forecasting approach is sufficient for the hackathon. The solution does not need to claim production-grade forecasting accuracy.

---

### 4.6 Anomaly Detection

The system should use historical, rental, usage, and/or telemetry data to detect anomalies.

The organizers specifically mentioned examples such as:

- Long idle hours
- Underutilized assets
- Unassigned equipment
- Equipment being used at an unexpected location
- Other abnormal usage conditions

Additional relevant anomalies may include:

- Missing operator assignment
- Missing site assignment
- Abnormally high engine temperature
- Abnormal fuel consumption
- Unsafe operator behavior
- Potential machine-health issues

An anomaly should ideally include supporting evidence rather than being presented as an unexplained AI result.

---

## 5. Smart Recommendations

The organizers expect the system to go beyond simply displaying data or identifying anomalies.

The system should provide useful operational recommendations where possible.

Examples include:

### Underutilization

If an asset is rented for an extended period but has very low productive runtime:

> Review the customer's requirement and consider early return or reallocation.

### Location mismatch

If an asset is assigned to one site but telemetry indicates operation at another location:

> Verify the asset's current location and assignment.

### Missing assignment

If an asset has no site or operator:

> Review the asset assignment and update the rental/operational records.

### Predictive maintenance

If telemetry indicates a potential machine issue, such as engine temperature increasing abnormally:

> Inspect the relevant machine system before continued operation.

### Asset allocation

If a site is forecast to require equipment and an asset is expected to become available:

> Consider allocating the returning/available asset to that site.

Recommendations should be supported by data available to the system.

---

## 6. Operator Safety

Safety was explicitly discussed as an important part of the Caterpillar problem.

The system may detect unsafe operating conditions using available telemetry/simulated data.

Examples include:

- Seatbelt not being worn while the machine is operating
- Unsafe operating behavior
- Proximity/environmental hazards where the required data is available

The system should be able to notify relevant users when a safety issue is detected.

The organizers also described an operator coaching concept.

When a safety issue occurs, the system may provide coaching material such as:

- Safety instructions
- A PDF
- A training document
- A video
- A short operator checklist

This is an important supporting capability but should not compromise the core asset-tracking, usage, anomaly, forecasting, and recommendation functionality.

---

## 7. Telemetry and Real-Time Simulation

The organizers indicated that a strong solution may simulate real-time machine telemetry.

Possible telemetry fields include:

- Timestamp
- Asset ID
- Location
- Engine/runtime hours
- Idle time
- Fuel consumption
- Engine temperature
- Seatbelt status
- Fault codes
- Other machine-health signals

The system may simulate:

- Live telemetry updates
- Location changes
- Machine operation
- Safety events
- Machine-health anomalies

Real Caterpillar machine integration is not required for the hackathon.

The purpose of simulation is to demonstrate how the system would behave when real machine data is available.

---

## 8. Official Sample Data

The following sample data was provided by the Caterpillar hackathon organizers in the supplied handout.

This data should be treated as official hackathon input.

| Equipment ID | Type | Site ID | Check-Out Date | Check-In Date | Engine Hours/Day | Idle Hours/Day | Operating Days | Last Operator ID |
|---|---|---|---|---|---:|---:|---:|---|
| EQX1001 | Excavator | S003 | 2025-04-01 | 2025-04-16 | 1.5 | 10 | 15 | OP101 |
| EQX1002 | Cater | NULL | 2025-03-01 | 2025-03-30 | 0 | 11 | 20 | NULL |
| EQX1003 | Bulldozer | S002 | 2025-02-15 | 2025-03-11 | 7.5 | 0.5 | 25 | OP203 |
| EQX1004 | Grader | S004 | 2025-05-05 | 2025-05-15 | 2 | 9 | 10 | OP106 |
| EQX1005 | Bulldozer | S006 | 2025-01-01 | 2025-01-31 | 8 | 0 | 30 | OP301 |
| EQX1006 | Grader | S001 | 2025-04-05 | 2025-04-23 | 3 | 6 | 18 | OP114 |
| EQX1007 | Excavator | NULL | 2025-03-20 | 2025-04-01 | 0 | 12 | 12 | NULL |

### Interpretation of NULL values

`NULL` values in the official data are meaningful operational states.

In particular:

- `Site ID = NULL` indicates that the asset has no recorded site assignment.
- `Last Operator ID = NULL` indicates that the asset has no recorded operator assignment.

These values must not simply be discarded or hidden.

They should remain visible to the system and may be used for anomaly detection and operational recommendations.

---

## 9. Expected Insights From the Official Dataset

The official data contains several conditions that can be used to demonstrate the system.

### EQX1001

- Excavator
- Assigned to S003
- 1.5 engine hours/day
- 10 idle hours/day

Potential insight:

- Relatively low productive usage compared with idle time
- Candidate for utilization analysis

---

### EQX1002

- Site is NULL
- Operator is NULL
- Engine hours/day = 0
- Idle hours/day = 11
- Operating days = 20

Potential insights:

- Missing site assignment
- Missing operator assignment
- Very low/no productive engine usage
- High idle time
- Potential underutilization
- Potential allocation/review candidate

This is a strong candidate for a primary anomaly demonstration.

---

### EQX1003

- Bulldozer
- Site S002
- 7.5 engine hours/day
- 0.5 idle hours/day
- Operator OP203

Potential insight:

- High productive usage
- Low idle time
- Useful as a healthy/high-utilization comparison asset

---

### EQX1004

- Grader
- Site S004
- 2 engine hours/day
- 9 idle hours/day
- Operator OP106

Potential insight:

- Relatively low productive usage
- High idle time
- Candidate for utilization analysis

---

### EQX1005

- Bulldozer
- Site S006
- 8 engine hours/day
- 0 idle hours/day
- Operator OP301

Potential insight:

- High productive usage
- Very low idle time
- Useful comparison/reference asset

---

### EQX1006

- Grader
- Site S001
- 3 engine hours/day
- 6 idle hours/day
- Operator OP114

Potential insight:

- Moderate usage
- Significant idle time
- Candidate for utilization analysis

---

### EQX1007

- Excavator
- Site is NULL
- Operator is NULL
- Engine hours/day = 0
- Idle hours/day = 12

Potential insights:

- Missing site assignment
- Missing operator assignment
- Very low/no productive engine usage
- Very high idle time
- Potential underutilization
- Potential reallocation candidate

---

## 10. Synthetic Data

The official sample data may be supplemented with deterministic synthetic data to demonstrate capabilities that are not represented in the supplied table.

Supplementary synthetic data may include:

- Telemetry time series
- GPS coordinates
- Location changes
- Engine temperature
- Fuel consumption
- Seatbelt events
- Fault codes
- Historical demand by site/equipment type
- Asset availability
- Returning assets
- Additional customers/sites/operators
- Notification events

Synthetic data should be:

- deterministic/reproducible
- internally consistent
- realistic enough for demonstration
- clearly distinguishable from official Caterpillar-provided data where appropriate

The official sample data must not be replaced by synthetic data.

---

## 11. Recommended Demonstration Scenarios

The final solution should support a coherent end-to-end story.

### Scenario A — Identify an underutilized/unassigned asset

Use an asset such as EQX1002 or EQX1007.

Show:

- missing site/operator assignment
- engine/runtime data
- idle time
- utilization
- detected anomaly
- evidence
- recommended action

---

### Scenario B — Detect a machine/telemetry anomaly

Simulate a telemetry event such as:

- engine overheating
- location mismatch
- unsafe seatbelt behavior
- abnormal fuel consumption

Show:

**Telemetry → Detection → Alert → Recommendation**

---

### Scenario C — Forecast future demand

Show historical demand for a site/equipment type and a forecast for a future period.

Show:

**Historical Demand → Forecast → Expected Requirement**

---

### Scenario D — Recommend an asset allocation

Combine:

- forecasted demand
- currently available assets
- expected returning assets

and produce an allocation/reallocation recommendation.

The important outcome is:

> The system should help the dealer decide which asset should go where and when.

---

### Scenario E — Trace asset lifecycle

Demonstrate:

**Dealership → Checkout → Customer/Site → Operator → Operation → Return/Check-in**

The system should retain a visible history/timeline of relevant asset events.

---

## 12. Optional/Additional Capabilities Mentioned by the Organizers

The organizers indicated that the following may strengthen the solution when the core requirements are already working:

- Simulated real-time telemetry
- QR scanning
- RFID simulation
- Live location updates
- Map view
- AI-assisted recommendations
- AI chat assistant
- Maintenance assistant
- Operator coaching content
- Richer analytics

These capabilities are secondary to the core requirements.

---

## 13. Product Expectations

The organizers emphasized that a strong solution should tell one complete story rather than demonstrate many disconnected features.

The system should allow a dealer/operations manager to move from:

**Visibility → Investigation → Detection → Explanation → Prediction → Action**

A useful conceptual flow is:

**Know → Detect → Explain → Predict → Act**

The system should help answer:

- What assets do I have?
- Where are they?
- Who is using them?
- Are they being used effectively?
- Is anything wrong?
- Why is it wrong?
- What is likely to happen next?
- What should I do?

---

## 14. Data-Backed Decisions

All important insights, anomalies, forecasts, and recommendations should be supported by available data.

The solution should avoid presenting unexplained AI outputs.

For example, instead of:

> "AI detected an issue."

Prefer:

> "EQX1002 has no assigned site or operator and has recorded 0 engine hours/day with 11 idle hours/day across 20 operating days."

followed by:

> "Recommendation: Review asset assignment and customer utilization; consider reallocation."

The evidence behind a recommendation should be inspectable.

---

## 15. MVP Priorities

Because the hackathon has limited implementation time, the solution should prioritize the following:

### Highest priority

- Asset dashboard
- Asset status and assignment visibility
- Check-in/check-out
- Asset lifecycle/history
- Usage and utilization
- Anomaly detection
- Alerts
- Demand forecasting
- Actionable recommendations

### Secondary priority

- Map
- Simulated real-time telemetry
- QR/RFID simulation
- Operator safety/coaching
- Additional analytics

### Lowest priority

- AI chatbot
- Real RFID hardware
- Real Caterpillar IoT integration
- Complex ML pipelines
- Production-grade distributed infrastructure
- Features unrelated to the core rental-tracking problem

A smaller, complete vertical slice is preferable to a large collection of unfinished features.

---

## 16. Hackathon Constraints

The available development time is approximately:

- Day 1: 11:30 AM – 7:00 PM
- Day 2: 9:00 AM – 12:00 PM

Actual working time is approximately 10.5 hours.

Therefore the implementation should favor:

- simplicity
- reliability
- explainability
- deterministic demo behavior
- rapid integration
- low infrastructure overhead

The solution is a hackathon MVP and does not need to represent a production Caterpillar platform.

---

## 17. Definition of a Strong Solution

A strong solution should demonstrate that the system can:

1. Show the rental fleet and current asset status.
2. Make every asset traceable through its rental lifecycle.
3. Show meaningful usage information.
4. Identify underutilized or incorrectly assigned assets.
5. Detect at least one meaningful anomaly.
6. Provide evidence for the anomaly.
7. Generate an actionable alert.
8. Forecast future equipment demand.
9. Connect the forecast to an asset allocation decision.
10. Demonstrate check-in/check-out.
11. Show that operational decisions are backed by data.

The final demonstration should leave the judges with a clear understanding that the system improves **asset visibility, utilization, safety, allocation, and rental operations**.

---

## 18. Implementation Freedom

The following are intentionally left open for the implementation planning phase:

- Frontend framework
- Backend framework
- Database technology
- API design
- Repository structure below the project boundary
- Telemetry transport
- Forecasting algorithm
- Anomaly thresholds
- Recommendation implementation
- Map implementation
- Deployment approach

These should be selected based on:

1. The actual repository state
2. The limited hackathon time
3. Reliability
4. Simplicity
5. Ease of integration
6. Demo quality

The implementation plan must not introduce complexity that does not materially improve the final solution.
