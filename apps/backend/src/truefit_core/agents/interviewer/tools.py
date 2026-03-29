"""
Tool declarations

These are the only ways the agent communicates state back to 
our system. The agent calls these; we respond with the result 
via send_tool_response.
"""



INTERVIEW_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "persist_answer",
                "description": (
                    "Call this when the candidate has fully answered the current question. "
                    "Persist the answer transcript to the interview record. "
                    "Call this before asking the next question."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question_id": {
                            "type": "string",
                            "description": "The UUID of the question being answered.",
                        },
                        "answer_transcript": {
                            "type": "string",
                            "description": "Full verbatim transcript of the candidate's answer.",
                        },
                        "duration_seconds": {
                            "type": "integer",
                            "description": "How long the candidate spoke in seconds.",
                        },
                    },
                    "required": ["question_id", "answer_transcript"],
                },
            },
            {
                "name": "record_question",
                "description": (
                    "Call this immediately after you ask a question, before waiting for the answer. "
                    "This persists the question text and returns a question_id you must use "
                    "when calling persist_answer."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question_text": {
                            "type": "string",
                            "description": "The exact question you just asked.",
                        },
                        "topic": {
                            "type": "string",
                            "description": "The skill or topic area this question targets.",
                        },
                        "is_follow_up": {
                            "type": "boolean",
                            "description": "True if this is a follow-up to the previous answer.",
                        },
                    },
                    "required": ["question_text"],
                },
            },
            {
                "name": "complete_interview",
                "description": (
                    "Call this when the interview is naturally complete — all questions asked "
                    "and answered, or max duration reached. Do NOT call this mid-interview."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "enum": [
                                "questions_exhausted",
                                "time_limit",
                                "candidate_ended",
                            ],
                            "description": "Why the interview is ending.",
                        },
                        "closing_remarks": {
                            "type": "string",
                            "description": "What you said to the candidate before ending.",
                        },
                    },
                    "required": ["reason"],
                },
            },
            {
                "name": "flag_interrupt",
                "description": (
                    "Call this when the candidate interrupts you mid-speech. "
                    "Use this to signal the system to stop your outgoing audio. "
                    "Then listen to what the candidate says and decide if it's a "
                    "clarification, a real answer, or noise."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interrupt_type": {
                            "type": "string",
                            "enum": ["clarification", "answer", "noise", "technical"],
                        },
                        "partial_transcript": {
                            "type": "string",
                            "description": "What you heard the candidate say so far.",
                        },
                    },
                    "required": ["interrupt_type"],
                },
            },
        ]
    }
]
