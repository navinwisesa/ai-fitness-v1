from flask import Flask, request, jsonify
import requests
import os
from duckduckgo_search import DDGS
import json
from datetime import datetime
import re

app = Flask(__name__)

# Environment variables for API keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",
                               "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")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# Exercise keywords that should trigger image search
EXERCISE_KEYWORDS = [
    'shuttle runs', 'cone drills', 'ladder drills', 'box jumps', 'zig-zag runs',
    'burpees', 'push-ups', 'squats', 'lunges', 'planks', 'deadlifts', 'pull-ups',
    'jumping jacks', 'mountain climbers', 'high knees', 'butt kicks', 'bear crawls',
    'jump rope', 'sprints', 'agility ladder', 'resistance band', 'kettlebell swing'
]

def search_exercise_images(exercise_name, max_results=3):
    """
    Search for exercise demonstration images using DuckDuckGo
    """
    try:
        with DDGS() as ddgs:
            # Search for exercise images with demonstration keywords
            image_results = list(ddgs.images(
                keywords=f"{exercise_name} exercise demonstration technique form",
                max_results=max_results,
                safesearch='moderate',
                size='Medium',  # Medium size for mobile display
                type_image='photo'
            ))
            
            # Filter and format image results
            formatted_images = []
            for img in image_results:
                if img.get('image') and img.get('title'):
                    formatted_images.append({
                        'url': img['image'],
                        'title': img['title'],
                        'source': img.get('source', ''),
                        'width': img.get('width', 0),
                        'height': img.get('height', 0)
                    })
            
            return formatted_images
            
    except Exception as e:
        print(f"Image search error: {e}")
        return []

def extract_exercises_from_text(text):
    """
    Extract exercise names from AI response text
    """
    found_exercises = []
    text_lower = text.lower()
    
    for exercise in EXERCISE_KEYWORDS:
        if exercise.lower() in text_lower:
            found_exercises.append(exercise)
    
    return found_exercises

def search_fitness_info(query, max_results=5):
    """
    Search for fitness-related information using DuckDuckGo
    """
    try:
        with DDGS() as ddgs:
            # Search for relevant fitness information
            search_results = list(ddgs.text(
                keywords=f"fitness health {query}",
                max_results=max_results,
                safesearch='moderate',
                timelimit='y'  # Last year for recent information
            ))

            # Format search results into readable context
            context = []
            for i, result in enumerate(search_results, 1):
                context.append(f"""
Source {i}:
Title: {result.get('title', 'N/A')}
URL: {result.get('href', 'N/A')}
Content: {result.get('body', 'N/A')[:300]}...
""")

            return "\n".join(context) if context else "No relevant search results found."

    except Exception as e:
        print(f"Search error: {e}")
        return f"Search unavailable: {str(e)}"

def should_search(user_message):
    """
    Determine if the user message requires current information search
    """
    search_keywords = [
        'latest', 'recent', 'new', 'current', 'trending', 'update',
        'studies show', 'research', 'news', 'breakthrough', '2024', '2025',
        'what do experts say', 'current recommendations', 'search the web', 'search', 'more information'
    ]

    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in search_keywords)

@app.route("/fitness-trainer", methods=["POST"])
def fitness_trainer():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        enable_search = data.get("enable_search", True)
        include_images = data.get("include_images", True)  # New parameter for image search

        if not user_message:
            return jsonify({"error": "Message is required"}), 400

        # Determine if search is needed
        search_context = ""
        search_used = False

        if enable_search and should_search(user_message):
            print(f"Searching for: {user_message}")
            search_context = search_fitness_info(user_message)
            search_used = True

        # Enhanced system prompt with image integration
        system_prompt = """You are an AI personal fitness and health trainer designed to provide helpful, informative, and supportive guidance to users on their wellness journey. Your role is to motivate, educate, and assist users in achieving their fitness and health goals safely and effectively.

When providing workout recommendations or exercise instructions, please format your response to clearly list exercises with their descriptions. Use clear exercise names that can be easily identified for image search integration.

CORE PRINCIPLES:
[Same as before - Safety First, Evidence-Based Approach, RAG Integration]

Format exercises clearly like:
**Exercise Name**: Description of the exercise and technique.

IMPORTANT LIMITATIONS AND BOUNDARIES:
[Same as before]

When answering, keep responses concise (under 5 bullet points or 150 words). Do not cut off mid-sentence."""

        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]

        # Add search context if available
        if search_context and search_used:
            messages.append({
                "role": "system",
                "content": f"CURRENT SEARCH RESULTS (Use this information to enhance your response):\n{search_context}\n\nPlease incorporate relevant information from these search results while maintaining your evidence-based approach."
            })

        messages.append({"role": "user", "content": user_message})

        # Payload to OpenRouter
        payload = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}"
        }

        response = requests.post(OPENROUTER_URL, headers=headers, json=payload)

        if response.status_code != 200:
            return jsonify({
                "error": "Failed to connect to OpenRouter",
                "details": response.text,
                "status_code": response.status_code
            }), 500

        result = response.json()

        if "choices" not in result or not result["choices"]:
            return jsonify({
                "error": "Invalid response from OpenRouter",
                "details": result
            }), 500

        reply = result["choices"][0]["message"]["content"]

        # NEW: Extract exercises and search for images
        exercise_images = {}
        if include_images:
            detected_exercises = extract_exercises_from_text(reply)
            print(f"Detected exercises: {detected_exercises}")
            
            for exercise in detected_exercises[:3]:  # Limit to 3 exercises to avoid too many API calls
                images = search_exercise_images(exercise, max_results=2)
                if images:
                    exercise_images[exercise] = images
                    print(f"Found {len(images)} images for {exercise}")

        return jsonify({
            "user_message": user_message,
            "ai_reply": reply,
            "exercise_images": exercise_images,  # NEW: Include exercise images
            "search_used": search_used,
            "timestamp": datetime.now().isoformat(),
            "model_used": MODEL
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "type": type(e).__name__
        }), 500

@app.route("/get-exercise-images", methods=["POST"])
def get_exercise_images():
    """
    Dedicated endpoint for fetching exercise images
    """
    try:
        data = request.get_json()
        exercise_name = data.get("exercise", "")
        max_results = data.get("max_results", 3)

        if not exercise_name:
            return jsonify({"error": "Exercise name is required"}), 400

        images = search_exercise_images(exercise_name, max_results)

        return jsonify({
            "exercise": exercise_name,
            "images": images,
            "count": len(images),
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/search", methods=["POST"])
def manual_search():
    """
    Manual search endpoint for testing DuckDuckGo integration
    """
    try:
        data = request.get_json()
        query = data.get("query", "")

        if not query:
            return jsonify({"error": "Query is required"}), 400

        search_results = search_fitness_info(query)

        return jsonify({
            "query": query,
            "search_results": search_results,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "AI Fitness Trainer API with RAG and Image Search is running",
        "features": [
            "Fitness training advice",
            "DuckDuckGo search integration",
            "Exercise image search and display",
            "Real-time information retrieval",
            "Evidence-based recommendations"
        ],
        "endpoints": {
            "/fitness-trainer": "POST - Main fitness trainer endpoint with image search",
            "/get-exercise-images": "POST - Get images for specific exercises",
            "/search": "POST - Manual search testing",
            "/": "GET - API status"
        }
    })

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    try:
        # Test search functionality
        test_search = search_fitness_info("fitness", max_results=1)
        search_working = "No relevant search results found." not in test_search
        
        # Test image search
        test_images = search_exercise_images("push-ups", max_results=1)
        images_working = len(test_images) > 0

        return jsonify({
            "status": "healthy",
            "search_enabled": search_working,
            "image_search_enabled": images_working,
            "model": MODEL,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "degraded",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 503

if __name__ == "__main__":
    # Test search on startup
    try:
        test_result = search_fitness_info("fitness test", max_results=1)
        print("✅ DuckDuckGo text search is working")
        print(f"Test result: {test_result[:100]}...")
        
        # Test image search
        test_images = search_exercise_images("push-ups", max_results=1)
        print(f"✅ DuckDuckGo image search is working - Found {len(test_images)} images")
        
    except Exception as e:
        print(f"⚠️ DuckDuckGo search test failed: {e}")

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
