import asyncio
from cover_letter_generator import generate_cover_letter

def test_cl():
    base_resume = {
        "name": "Jalal Khan",
        "contact": {"email": "test@test.com", "phone": "123", "location": "Remote"},
        "summary": "Full stack engineer",
        "skills": ["Python", "JavaScript"],
        "experience": [{"company": "Tech", "title": "SE", "description": "Did things"}]
    }
    jd = "We are looking for a Senior Software Engineer to build AI apps."
    company = "TechCorp"
    role = "Senior Software Engineer"
    
    res = generate_cover_letter(base_resume, jd, company, role)
    print("OUTPUT:")
    print(res["cover_letter_text"])

test_cl()
