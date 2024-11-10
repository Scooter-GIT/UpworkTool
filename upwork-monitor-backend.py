# main.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
import os
from threading import Thread
import sqlite3
from contextlib import contextmanager

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
def init_db():
    with sqlite3.connect('jobs.db') as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS jobs
        (id TEXT PRIMARY KEY, title TEXT, description TEXT, url TEXT, 
         posted_date TEXT, matched_date TEXT)
        ''')
        
        conn.execute('''
        CREATE TABLE IF NOT EXISTS settings
        (id INTEGER PRIMARY KEY, skills TEXT, check_interval INTEGER)
        ''')

@contextmanager
def get_db():
    conn = sqlite3.connect('jobs.db')
    try:
        yield conn
    finally:
        conn.close()

init_db()

class Settings(BaseModel):
    skills: List[str]
    check_interval: int = 300  # 5 minutes default

class JobMatch(BaseModel):
    id: str
    title: str
    description: str
    url: str
    posted_date: str
    matched_date: str

def scrape_upwork_jobs(skills):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    }
    
    jobs = []
    base_url = "https://www.upwork.com/nx/jobs/search/"
    
    for skill in skills:
        try:
            response = requests.get(
                f"{base_url}?q={skill}&sort=recency",
                headers=headers
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # Update these selectors based on current Upwork HTML structure
            job_elements = soup.find_all('div', {'class': 'job-tile'})
            
            for job in job_elements:
                job_id = job.get('data-job-id', '')
                if not job_id:
                    continue
                    
                title = job.find('h4', {'class': 'job-title'})
                description = job.find('div', {'class': 'job-description'})
                
                if title and description:
                    jobs.append({
                        'id': job_id,
                        'title': title.text.strip(),
                        'description': description.text.strip(),
                        'url': f"https://www.upwork.com/jobs/{job_id}",
                        'posted_date': datetime.now().isoformat(),
                        'matched_date': datetime.now().isoformat()
                    })
            
            time.sleep(2)  # Rate limiting
            
        except Exception as e:
            print(f"Error scraping jobs for skill {skill}: {e}")
            continue
    
    return jobs

def monitor_jobs():
    while True:
        try:
            with get_db() as conn:
                settings = conn.execute('SELECT skills, check_interval FROM settings WHERE id = 1').fetchone()
                
                if not settings:
                    time.sleep(60)
                    continue
                
                skills = json.loads(settings[0])
                check_interval = settings[1]
                
                new_jobs = scrape_upwork_jobs(skills)
                
                for job in new_jobs:
                    conn.execute('''
                    INSERT OR IGNORE INTO jobs (id, title, description, url, posted_date, matched_date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''', (job['id'], job['title'], job['description'], job['url'], 
                         job['posted_date'], job['matched_date']))
                
                conn.commit()
                
                time.sleep(check_interval)
                
        except Exception as e:
            print(f"Error in monitor thread: {e}")
            time.sleep(60)

# Start monitoring thread
monitor_thread = Thread(target=monitor_jobs, daemon=True)
monitor_thread.start()

@app.post("/settings")
async def update_settings(settings: Settings):
    try:
        with get_db() as conn:
            conn.execute('DELETE FROM settings')
            conn.execute(
                'INSERT INTO settings (id, skills, check_interval) VALUES (1, ?, ?)',
                (json.dumps(settings.skills), settings.check_interval)
            )
            conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/settings")
async def get_settings():
    with get_db() as conn:
        result = conn.execute('SELECT skills, check_interval FROM settings WHERE id = 1').fetchone()
        if result:
            return {
                "skills": json.loads(result[0]),
                "check_interval": result[1]
            }
        return {"skills": [], "check_interval": 300}

@app.get("/jobs")
async def get_jobs(limit: int = 50):
    with get_db() as conn:
        jobs = conn.execute(
            'SELECT * FROM jobs ORDER BY matched_date DESC LIMIT ?',
            (limit,)
        ).fetchall()
        
        return [
            {
                "id": job[0],
                "title": job[1],
                "description": job[2],
                "url": job[3],
                "posted_date": job[4],
                "matched_date": job[5]
            }
            for job in jobs
        ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
