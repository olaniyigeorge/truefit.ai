import asyncio
from src.truefit_infra.llm.gemini_llm import GeminiLLMAdapter
from src.truefit_core.application.ports import ResumeEvaluationRequest

async def main():
    llm = GeminiLLMAdapter()
    result = await llm.evaluate_resume(ResumeEvaluationRequest(
        resume_text="5 years Python, Django, REST APIs, PostgreSQL. Built microservices at scale.",
        job_title="Senior Backend Engineer",
        job_description="We need a Python expert to build APIs.",
        required_skills=["Python", "Django", "PostgreSQL"],
        experience_level="senior",
    ))
    print(result)

asyncio.run(main())
