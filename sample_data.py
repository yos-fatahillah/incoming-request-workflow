"""
sample_data.py
--------------
Synthetic dataset of incoming requests (AI-generated, no proprietary/client
data), covering all four branch types plus a couple of ambiguous edge cases
to demonstrate the low-confidence escalation override.
"""

SAMPLE_REQUESTS = [
    {
        "id": "REQ-1001",
        "expected_branch": "Complaint",
        "text": ("I was charged twice for my subscription this month and it's the second "
                  "time this has happened. This is really disappointing and I'd like a refund "
                  "for the duplicate charge."),
    },
    {
        "id": "REQ-1002",
        "expected_branch": "General Enquiry",
        "text": ("Hi, just wondering what your customer support hours are on weekends? "
                  "Also, do you offer support in French?"),
    },
    {
        "id": "REQ-1003",
        "expected_branch": "Service Request",
        "text": ("Can you please update the delivery address on my last order? I moved "
                  "house last week and the package hasn't shipped yet."),
    },
    {
        "id": "REQ-1004",
        "expected_branch": "Escalation",
        "text": ("This is the THIRD time I'm contacting you about the same billing error "
                  "and nobody has fixed it. I want to speak to a manager immediately or I "
                  "will be taking this to my bank and reporting you to the regulator."),
    },
    {
        "id": "REQ-1005",
        "expected_branch": "Service Request",
        "text": ("I'd like to upgrade my current plan to the Pro tier starting next billing "
                  "cycle please."),
    },
    {
        "id": "REQ-1006",
        "expected_branch": "General Enquiry",
        "text": "Do you have a mobile app, and is it available on both iOS and Android?",
    },
    {
        "id": "REQ-1007",
        "expected_branch": "Complaint",
        "text": ("The replacement part I received was the wrong model and now my order is "
                  "delayed by another two weeks. Very poor service on this order."),
    },
    {
        "id": "REQ-1008",
        "expected_branch": "Escalation",
        "text": ("I am extremely upset. I've already emailed twice with no response, this "
                  "is unacceptable, and if this isn't resolved today I'm cancelling my "
                  "account immediately and posting about this on social media."),
    },
    {
        "id": "REQ-1009",
        "expected_branch": "Service Request",
        "text": "Please reset my account password, I've been locked out since this morning.",
    },
    {
        "id": "REQ-1010",
        # Deliberately ambiguous/short to trigger low-confidence override demo
        "expected_branch": "Escalation (override)",
        "text": "hey. this. still not fixed. do something.",
    },
]
