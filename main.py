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

# Fitness-related terms that indicate image-worthy content
FITNESS_INDICATORS = [
    'exercise', 'workout', 'stretch', 'movement', 'pose', 'position', 'form',
    'technique', 'drill', 'routine', 'training', 'bicep', 'tricep', 'chest',
    'back', 'shoulder', 'leg', 'core', 'abs', 'glute', 'cardio', 'strength',
    'flexibility', 'mobility', 'yoga', 'pilates', 'calisthenics', 'bodyweight',
    'dumbbell', 'barbell', 'kettlebell', 'resistance', 'band', 'machine'
]

def search_exercise_images(exercise_name, max_results=3):
    """
    Search for exercise demonstration images/GIFs using DuckDuckGo with priority on animated content
    """
    try:
        with DDGS() as ddgs:
            # First attempt: Search specifically for GIFs and animated demonstrations
            gif_results = []
            try:
                gif_search_results = list(ddgs.images(
                    keywords=f"{exercise_name} exercise demonstration gif animated how to",
                    max_results=max_results * 2,  # Get more results to filter
                    safesearch='moderate',
                    size='Medium'
                ))
                
                # Filter for likely GIFs/animated content
                for img in gif_search_results:
                    if img.get('image') and img.get('title'):
                        url = img['image'].lower()
                        title = img['title'].lower()
                        
                        # Check if it's likely a GIF or animated content
                        is_animated = (
                            url.endswith('.gif') or 
                            '.gif' in url or
                            'gif' in title or
                            'animated' in title or
                            'animation' in title or
                            'demo' in title or
                            'demonstration' in title
                        )
                        
                        if is_animated:
                            gif_results.append({
                                'url': img['image'],
                                'title': img['title'],
                                'source': img.get('source', ''),
                                'width': img.get('width', 0),
                                'height': img.get('height', 0),
                                'type': 'animated'
                            })
                
                print(f"Found {len(gif_results)} animated results for {exercise_name}")
                
            except Exception as gif_error:
                print(f"GIF search failed for {exercise_name}: {gif_error}")
            
            # If we have enough GIFs, return them
            if len(gif_results) >= max_results:
                return gif_results[:max_results]
            
            # Second attempt: Search for regular demonstration images
            static_results = []
            remaining_needed = max_results - len(gif_results)
            
            if remaining_needed > 0:
                try:
                    static_search_results = list(ddgs.images(
                        keywords=f"{exercise_name} exercise technique form proper demonstration",
                        max_results=remaining_needed * 2,
                        safesearch='moderate',
                        size='Medium',
                        type_image='photo'
                    ))
                    
                    # Filter static images, avoiding duplicates from GIF search
                    existing_urls = {img['url'] for img in gif_results}
                    
                    for img in static_search_results:
                        if (img.get('image') and 
                            img.get('title') and 
                            img['image'] not in existing_urls):
                            
                            static_results.append({
                                'url': img['image'],
                                'title': img['title'],
                                'source': img.get('source', ''),
                                'width': img.get('width', 0),
                                'height': img.get('height', 0),
                                'type': 'static'
                            })
                            
                            if len(static_results) >= remaining_needed:
                                break
                    
                    print(f"Found {len(static_results)} static results for {exercise_name}")
                    
                except Exception as static_error:
                    print(f"Static image search failed for {exercise_name}: {static_error}")
            
            # Combine results: GIFs first, then static images
            combined_results = gif_results + static_results[:remaining_needed]
            
            print(f"Total results for {exercise_name}: {len(combined_results)} ({len(gif_results)} animated, {len(static_results)} static)")
            return combined_results[:max_results]
            
    except Exception as e:
        print(f"Image search error for {exercise_name}: {e}")
        return []

def should_include_images(user_message, ai_response):
    """
    Determine if the content warrants exercise images based on context
    """
    combined_text = f"{user_message} {ai_response}".lower()
    
    # Check for fitness-related indicators
    fitness_related = any(indicator in combined_text for indicator in FITNESS_INDICATORS)
    
    # Check for instructional language that suggests demonstrations would be helpful
    instructional_phrases = [
        'how to', 'technique', 'form', 'proper', 'correct', 'demonstration',
        'perform', 'execute', 'do this', 'steps', 'position', 'posture'
    ]
    
    instructional = any(phrase in combined_text for phrase in instructional_phrases)
    
    return fitness_related and (instructional or 'workout' in combined_text or 'exercise' in combined_text)

def extract_exercises_from_text(text):
    """
    Intelligently extract exercise/movement names from AI response text using NLP techniques
    """
    import re
    
    # Common exercise patterns
    exercise_patterns = [
        # Pattern 1: **Exercise Name**: description
        r'\*\*([^*]+)\*\*:',
        # Pattern 2: 1. Exercise Name - description  
        r'\d+\.\s*([^-\n]+)(?:\s*[-–]|\n)',
        # Pattern 3: Exercise Name (standalone with context)
        r'(?:perform|do|try|practice|start with|include)\s+([^,.!?\n]+?)(?:\s+(?:exercise|stretch|movement|pose))?(?:[,.!?\n]|$)',
        # Pattern 4: "the [exercise name]" pattern
        r'the\s+([^,.!?\n]{2,30}?)(?:\s+(?:exercise|stretch|movement|pose|position))',
    ]
    
    found_exercises = []
    
    for pattern in exercise_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            exercise_name = match.group(1).strip()
            
            # Clean up the extracted name
            exercise_name = re.sub(r'^(a|an|the)\s+', '', exercise_name, flags=re.IGNORECASE)
            exercise_name = re.sub(r'\s+', ' ', exercise_name)
            
            # Validate it's likely an exercise/stretch
            if _is_valid_exercise_name(exercise_name):
                found_exercises.append(exercise_name)
    
    # Remove duplicates while preserving order
    unique_exercises = []
    seen = set()
    for exercise in found_exercises:
        lower_exercise = exercise.lower()
        if lower_exercise not in seen and len(lower_exercise) > 2:
            seen.add(lower_exercise)
            unique_exercises.append(exercise)
    
    return unique_exercises[:5]  # Limit to 5 to avoid too many API calls

def _is_valid_exercise_name(name):
    """
    Validate if extracted text is likely an exercise name
    """
    if not name or len(name) < 3 or len(name) > 50:
        return False
    
    # Skip if it's just common words
    common_words = {'and', 'or', 'but', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'will', 'would', 'should', 'could'}
    words = name.lower().split()
    if all(word in common_words for word in words):
        return False
    
    # Check if it contains fitness-related terms or action words
    fitness_terms = FITNESS_INDICATORS + [
        'push', 'pull', 'lift', 'raise', 'lower', 'bend', 'twist', 'rotate', 'hold',
        'press', 'curl', 'extension', 'flexion', 'crunch', 'raise', 'fly', 'row',
        'squat', 'lunge', 'plank', 'bridge', 'twist', 'stretch', 'reach'
    ]
    
    name_lower = name.lower()
    has_fitness_term = any(term in name_lower for term in fitness_terms)
    
    # Also check for common exercise naming patterns
    exercise_patterns = [
        r'\w+\s+(press|curl|raise|extension|stretch|pose)',
        r'(morning|evening|daily|basic|simple|easy)\s+\w+',
        r'\w+\s+(workout|routine|exercise)',
        r'(bicep|tricep|chest|back|shoulder|leg|core|ab)\s+\w+',
    ]
    
    has_pattern = any(re.search(pattern, name_lower) for pattern in exercise_patterns)
    
    return has_fitness_term or has_pattern

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

        # NEW: Extract exercises and search for images (only if content warrants it)
        exercise_images = {}
        if include_images and should_include_images(user_message, reply):
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
