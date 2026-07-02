# DEXTER: Strategy B Institutional Scaling Blueprint

This document details the architecture required to scale Dexter across 5–10 "Fleets" (100–200 accounts) while maintaining legal compliance and optimizing tax treatment.

---

## 1. Legal Architecture: Bypassing the "20 Account" Rule
Prop firms like Apex limit accounts to **20 per household**. To scale to 100 or 200 accounts, you must move from a "Natural Person" setup to a **"Corporate Entity"** setup.

### The LLC Partition Strategy
*   **The Concept:** Each LLC is a separate "Legal Person." Under current regulations, if you own 5 separate LLCs, each LLC is technically its own entity allowed to hold its own fleet of accounts.
*   **EINs vs SSNs:** You do not use your Social Security Number for these fleets. You obtain an **EIN (Employer Identification Number)** for each LLC. This is what you provide to the prop firm during the PA (Performance Account) setup.
*   **Address Management:** Some firms are strict about physical addresses. Professionals often use **Registered Agents** or separate business addresses for each LLC to ensure the "Household" rule isn't accidentally tripped by a shared mailing address.

---

## 2. Technical Organization: The "Partitioned VM" Model
Running 200 accounts on one terminal will cause "Execution Lag," which leads to massive slippage. You must organize your logins across **Virtual Machines (VMs)**.

### Fleet Organization (Per LLC)
*   **Hardware:** A high-performance server (e.g., 64GB RAM, 16-Core CPU).
*   **Partitioning:** You run 5–10 separate VM instances.
    *   **VM #1 (LLC Alpha):** Controls 20 accounts.
    *   **VM #2 (LLC Beta):** Controls 20 accounts.
*   **Login Isolation:** Each VM has its own unique **IP Address** (via a proxy or VPN) and a unique **MAC Address** (virtual hardware ID). This ensures the Prop Firm sees each LLC as a completely distinct trader coming from a different location.

---

## 3. Account & Login Management
With 200 accounts, you cannot manage passwords manually. 

*   **Master Fleet Key:** Dexter’s `fleet_config.yaml` is programmed to store encrypted API keys for each LLC fleet.
*   **The "Lead" Account Logic:** In each fleet, you designate one **Master Account**. The other 19 are **Followers**. Dexter only sends one signal; the copier (built-in or Replikanto) blasts it to the other 19.

---

## 4. IRS: Trader Tax Status (TTS) Qualification
To make this scale profitable, you must qualify for **Trader Tax Status (TTS)**. This transforms your trading from a "hobby" into a "business" in the eyes of the IRS.

### The Criteria for TTS
The IRS does not have a formal form for TTS. You qualify by **demonstrating consistent behavior**:
1.  **Substantial Activity:** You must trade at least 4 days a week.
2.  **Continuity:** You must trade for the majority of the year (no long breaks).
3.  **Profit Intent:** You must intend to make a living from the activity (Dexter’s audit logs prove this intent).
4.  **Business Equipment:** You must have a dedicated setup (The VM server and Dexter software).

### The "Holy Grail": Section 475(f) MTM Election
Once you have TTS, you can elect **Mark-to-Market (MTM)** accounting.
*   **No Wash Sales:** You can ignore the "30-day wash sale" rule, which is a nightmare for scalpers.
*   **Ordinary Loss Treatment:** If you have a bad year, you can deduct **unlimited losses** against your other income (standard traders are limited to $3,000/year).
*   **Business Deductions:** You can write off your server costs, AI API fees, and LLC filing fees as business expenses.

---

## 5. Operational Roadmap (Step-by-Step)

| Phase | Action | Goal |
| :--- | :--- | :--- |
| **Step 1** | Form LLC #1 & Obtain EIN | Establish the corporate "Person." |
| **Step 2** | Set up a Dedicated VM | Isolate the technical environment. |
| **Step 3** | Link 20 Accounts to EIN | Fill the first "Fleet." |
| **Step 4** | Deploy Dexter Master | Begin automated "Fleet Execution." |
| **Step 5** | Repeat for LLC #2 - #10 | Scale to the 200-account target. |

---

### 🚦 Important Compliance Warning
Always consult with a **CPA specializing in trading** (like GreenTraderTax) before filing for TTS. While Dexter provides the technical edge, you need professional tax advice to ensure your LLC partitioning is structured correctly for your specific state.
