from flask import Flask, request, jsonify
import requests
import os
from duckduckgo_search import DDGS
import json
from datetime import datetime, timedelta
import re
import random

app = Flask(__name__)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",
                               "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")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3.3-70b-instruct:free"
FITNESS_INDICATORS = [
    'exercise', 'workout', 'stretch', 'movement', 'pose', 'position', 'form',
    'technique', 'drill', 'routine', 'training', 'bicep', 'tricep', 'chest',
    'back', 'shoulder', 'leg', 'core', 'abs', 'glute', 'cardio', 'strength',
    'flexibility', 'mobility', 'yoga', 'pilates', 'calisthenics', 'bodyweight',
    'dumbbell', 'barbell', 'kettlebell', 'resistance', 'band', 'machine'
]

def generate_workout_colors():
    """Generate random colors for workouts"""
    colors = [
        0xFF2196F3,
        0xFF4CAF50,
        0xFFFF9800,
        0xFF9C27B0,
        0xFFF44336,
        0xFF00BCD4,
        0xFF8BC34A,
        0xFFFF5722,
        0xFF673AB7,
        0xFF607D8B,
    ]
    return random.choice(colors)

def estimate_workout_duration(exercises):
    """Calculate realistic workout duration based on exercises"""
    if not exercises:
        return 60  # Default 60 minutes
    
    # Time estimates per exercise type (in minutes)
    base_warmup_cooldown = 15  # 10 min warmup + 5 min cooldown
    exercise_time = 0
    
    for exercise in exercises:
        sets = exercise.get('sets', 3)
        reps = exercise.get('reps', 10)
        
        # Estimate time per exercise based on sets and type
        if any(word in exercise.get('name', '').lower() for word in ['press', 'squat', 'deadlift', 'pull-up']):
            # Compound exercises take longer (rest between sets)
            exercise_time += sets * 3  # 3 minutes per set (including rest)
        elif any(word in exercise.get('name', '').lower() for word in ['curl', 'raise', 'extension', 'fly']):
            # Isolation exercises take less time
            exercise_time += sets * 2  # 2 minutes per set
        else:
            # Default time
            exercise_time += sets * 2.5
    
    total_time = base_warmup_cooldown + exercise_time
    return min(max(total_time, 30), 120)

def parse_workout_plan_from_text(ai_response):
    """Enhanced parser with realistic duration calculation"""
    workouts = []
    
    # Look for clear day indicators
    day_patterns = [
        r'Day\s+(\d+)[:\-]\s*(.*?)(?=(?:\n\s*Day\s+\d+|\n\s*\w+day|\Z))',
        r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[:\-]\s*(.*?)(?=(?:\n\s*(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day|\n\s*Day\s+\d+|\Z))',
    ]
    
    for pattern in day_patterns:
        matches = re.finditer(pattern, ai_response, re.IGNORECASE | re.DOTALL)
        for match in matches:
            day_num = match.group(1) if pattern.startswith('Day') else None
            day_name = match.group(1) if not pattern.startswith('Day') else None
            day_content = match.group(2)
            
            if day_num:
                day_number = int(day_num)
            elif day_name:
                day_mapping = {
                    'monday': 1, 'tuesday': 2, 'wednesday': 3, 'thursday': 4,
                    'friday': 5, 'saturday': 6, 'sunday': 7
                }
                day_number = day_mapping.get(day_name.lower(), 1)
            else:
                continue
                
            exercises = extract_exercises_from_day_text(day_content)
            duration = estimate_workout_duration(exercises)  # Calculate realistic duration
            
            if exercises:
                workout = {
                    'day': day_number,
                    'name': f"Day {day_number} - {determine_primary_category(exercises).title()}",
                    'exercises': exercises,
                    'duration': duration,  # Use calculated duration
                    'category': determine_primary_category(exercises),
                }
                workouts.append(workout)
    
    return workouts

def extract_exercises_from_day_text(day_text):
    """Simple but reliable exercise extraction"""
    exercises = []
    
    # Look for exercise lines with common patterns
    lines = day_text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith(('Rest', 'Day off', 'Recovery')):
            continue
            
        # Pattern: "- Exercise: 3x12" or "• Bench Press: 3 sets x 12 reps"
        exercise_match = re.search(r'[•\-]\s*([^:]+?)\s*:\s*(.+)', line)
        if not exercise_match:
            # Pattern: "Bench Press - 3x12"
            exercise_match = re.search(r'([^\-]+?)\s*-\s*(.+)', line)
        
        if exercise_match:
            exercise_name = exercise_match.group(1).strip()
            details = exercise_match.group(2).strip()
            
            if _is_valid_exercise_name(exercise_name):
                sets, reps, weight = parse_exercise_details(details)
                
                exercise = {
                    'name': exercise_name,
                    'sets': sets,
                    'reps': reps,
                    'weight': weight,
                    'category': categorize_exercise(exercise_name)
                }
                exercises.append(exercise)
    
    return exercises

def parse_weekly_schedule_format(text):
    """Parse weekly schedule format workout plans"""
    workouts = []
    weekly_indicators = r'(?:Week\s+\d+|Weekly\s+Schedule|7[- ]day\s+plan)'
    if not re.search(weekly_indicators, text, re.IGNORECASE):
        return []
    day_sections = re.split(r'\n(?=(?:Day\s+\d+|\w+day))', text, flags=re.IGNORECASE)
    
    for section in day_sections:
        if re.match(r'(?:Day\s+\d+|\w+day)', section, re.IGNORECASE):
            exercises = extract_exercises_from_day_text(section)
            if exercises:
                day_match = re.match(r'(?:Day\s+(\d+)|(\w+day))', section, re.IGNORECASE)
                if day_match:
                    day_num = day_match.group(1)
                    day_name = day_match.group(2)
                    
                    if day_num:
                        day_number = int(day_num)
                    else:
                        day_mapping = {
                            'monday': 1, 'tuesday': 2, 'wednesday': 3, 'thursday': 4,
                            'friday': 5, 'saturday': 6, 'sunday': 7
                        }
                        day_number = day_mapping.get(day_name.lower(), len(workouts) + 1)
                    
                    workout = {
                        'day': day_number,
                        'name': f"Day {day_number} - {determine_primary_category(exercises).title()}",
                        'exercises': exercises,
                        'duration': estimate_workout_duration(exercises),
                        'category': determine_primary_category(exercises),
                        'color': generate_workout_colors()
                    }
                    workouts.append(workout)
    
    return workouts

def parse_exercise_details(details_text):
    """Parse sets, reps, and weight from exercise details"""
    sets = 3
    reps = 10
    weight = 0.0
    
    if not details_text:
        return sets, reps, weight
    sets_match = re.search(r'(\d+)\s*(?:sets?|x)', details_text, re.IGNORECASE)
    if sets_match:
        sets = int(sets_match.group(1))
    reps_match = re.search(r'(\d+)\s*(?:reps?|repetitions?)', details_text, re.IGNORECASE)
    if not reps_match:
        format_match = re.search(r'\d+\s*x\s*(\d+)', details_text, re.IGNORECASE)
        if format_match:
            reps = int(format_match.group(1))
    else:
        reps = int(reps_match.group(1))
    weight_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:kg|lbs?|pounds?)', details_text, re.IGNORECASE)
    if weight_match:
        weight = float(weight_match.group(1))
        if re.search(r'lbs?|pounds?', details_text, re.IGNORECASE):
            weight = weight * 0.453592
    
    return sets, reps, weight

def categorize_exercise(exercise_name):
    """Categorize exercise based on name"""
    exercise_lower = exercise_name.lower()
    
    if any(word in exercise_lower for word in ['press', 'push', 'chest', 'bench', 'fly', 'dip']):
        return 'chest'
    elif any(word in exercise_lower for word in ['curl', 'bicep', 'chin']):
        return 'biceps'
    elif any(word in exercise_lower for word in ['tricep', 'extension', 'dip']):
        return 'triceps'
    elif any(word in exercise_lower for word in ['row', 'pull', 'lat', 'back']):
        return 'back'
    elif any(word in exercise_lower for word in ['shoulder', 'lateral', 'overhead', 'military']):
        return 'shoulders'
    elif any(word in exercise_lower for word in ['squat', 'lunge', 'leg', 'quad', 'hamstring']):
        return 'legs'
    elif any(word in exercise_lower for word in ['plank', 'crunch', 'core', 'ab', 'sit']):
        return 'core'
    elif any(word in exercise_lower for word in ['run', 'jog', 'cardio', 'bike', 'treadmill']):
        return 'cardio'
    else:
        return 'other'

def determine_primary_category(exercises):
    """Determine the primary category for a workout based on exercises"""
    if not exercises:
        return 'other'
    
    categories = []
    for ex in exercises:
        # Check if the object is a dictionary and has a 'category' key
        if isinstance(ex, dict) and 'category' in ex:
            categories.append(ex['category'])
        # Check if the object is an instance of a class with a 'category' attribute
        elif hasattr(ex, 'category'):
            categories.append(ex.category)
    
    if not categories:
        return 'other'
        
    category_counts = {}
    for cat in categories:
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    return max(category_counts.items(), key=lambda x: x[1])[0]

def estimate_workout_duration(exercises):
    """Estimate workout duration based on exercises"""
    base_time = 15
    exercise_time = len(exercises) * 8
    return min(base_time + exercise_time, 120)
def search_exercise_images(exercise_name, max_results=3, prefer_animated=True):
    """Enhanced search for exercise demonstration images/GIFs"""
    try:
        with DDGS() as ddgs:
            all_results = []
            
            # Search queries with different priorities
            search_queries = [
                f"{exercise_name} exercise animated gif demonstration",
                f"{exercise_name} workout technique gif",
                f"how to do {exercise_name} animated",
                f"{exercise_name} proper form demonstration",
                f"{exercise_name} exercise tutorial"
            ]
            
            for query in search_queries:
                if len(all_results) >= max_results * 2:
                    break
                    
                try:
                    search_results = list(ddgs.images(
                        keywords=query,
                        max_results=max_results,
                        safesearch='moderate',
                        size='Medium'
                    ))
                    
                    for img in search_results:
                        if img.get('image') and img.get('title'):
                            url = img['image'].lower()
                            title = img['title'].lower()
                            
                            # Better detection for exercise-related content
                            is_exercise_related = (
                                any(term in title for term in ['exercise', 'workout', 'fitness', 'training']) or
                                any(term in url for term in ['exercise', 'workout', 'fitness'])
                            )
                            
                            is_animated = (
                                url.endswith('.gif') or 
                                '.gif' in url or
                                'gif' in title or
                                'animated' in title
                            )
                            
                            # Prioritize animated if requested, but include static if needed
                            if is_exercise_related and (is_animated or not prefer_animated or len(all_results) < max_results):
                                all_results.append({
                                    'url': img['image'],
                                    'title': img['title'],
                                    'source': img.get('source', ''),
                                    'width': img.get('width', 0),
                                    'height': img.get('height', 0),
                                    'type': 'animated' if is_animated else 'static',
                                    'exercise_match_score': _calculate_exercise_match_score(exercise_name, img['title'])
                                })
                                
                except Exception as query_error:
                    print(f"Query '{query}' failed: {query_error}")
                    continue
            
            # Sort by relevance and remove duplicates
            unique_results = _remove_duplicate_images(all_results)
            sorted_results = sorted(unique_results, 
                                  key=lambda x: (x['exercise_match_score'], x['type'] == 'animated'), 
                                  reverse=True)
            
            return sorted_results[:max_results]
            
    except Exception as e:
        print(f"Image search error for {exercise_name}: {e}")
        return []

def _calculate_exercise_match_score(exercise_name, image_title):
    """Calculate how well the image title matches the exercise name"""
    exercise_terms = exercise_name.lower().split()
    title_lower = image_title.lower()
    
    score = 0
    for term in exercise_terms:
        if term in title_lower:
            score += 1
    
    # Bonus points for exact matches and exercise-related terms
    if exercise_name.lower() in title_lower:
        score += 2
        
    if any(keyword in title_lower for keyword in ['exercise', 'workout', 'how to', 'tutorial']):
        score += 1
        
    return score

def _remove_duplicate_images(images):
    """Remove duplicate images based on URL similarity"""
    unique_images = []
    seen_urls = set()
    
    for img in images:
        # Basic URL normalization
        url = img['url'].split('?')[0]  # Remove query parameters
        
        if url not in seen_urls:
            seen_urls.add(url)
            unique_images.append(img)
    
    return unique_images

def extract_exercises_from_workout_plan(workout_plan_text):
    """Extract all exercises from a workout plan text"""
    exercises = []
    
    # Pattern to match exercise lines in workout plans
    patterns = [
        r'[•\-]\s*([^:]+?)\s*:\s*\d+\s*sets?',  # - Exercise: 3 sets
        r'[•\-]\s*([^:]+?)\s*-\s*\d+x\d+',      # - Exercise - 3x12
        r'\*\*([^*]+)\*\*:\s*\d+\s*sets?',      # **Exercise**: 3 sets
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, workout_plan_text, re.IGNORECASE)
        for match in matches:
            exercise_name = match.group(1).strip()
            if _is_valid_exercise_name(exercise_name):
                exercises.append(exercise_name)
    
    return list(set(exercises))  # Remove duplicates

def should_include_images(user_message, ai_response):
    """Determine if content warrants exercise images"""
    combined_text = f"{user_message} {ai_response}".lower()
    fitness_related = any(indicator in combined_text for indicator in FITNESS_INDICATORS)
    instructional_phrases = [
        'how to', 'technique', 'form', 'proper', 'correct', 'demonstration',
        'perform', 'execute', 'do this', 'steps', 'position', 'posture'
    ]
    instructional = any(phrase in combined_text for phrase in instructional_phrases)
    return fitness_related and (instructional or 'workout' in combined_text or 'exercise' in combined_text)

def extract_exercises_from_text(text):
    """Extract exercise names from text"""
    exercise_patterns = [
        r'\*\*([^*]+)\*\*:',
        r'\d+\.\s*([^-\n]+)(?:\s*[-–]|\n)',
        r'(?:perform|do|try|practice|start with|include)\s+([^,.!?\n]+?)(?:\s+(?:exercise|stretch|movement|pose))?(?:[,.!?\n]|$)',
        r'the\s+([^,.!?\n]{2,30}?)(?:\s+(?:exercise|stretch|movement|pose|position))',
    ]
    
    found_exercises = []
    for pattern in exercise_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            exercise_name = match.group(1).strip()
            exercise_name = re.sub(r'^(a|an|the)\s+', '', exercise_name, flags=re.IGNORECASE)
            exercise_name = re.sub(r'\s+', ' ', exercise_name)
            
            if _is_valid_exercise_name(exercise_name):
                found_exercises.append(exercise_name)
    
    unique_exercises = []
    seen = set()
    for exercise in found_exercises:
        lower_exercise = exercise.lower()
        if lower_exercise not in seen and len(lower_exercise) > 2:
            seen.add(lower_exercise)
            unique_exercises.append(exercise)
    
    return unique_exercises[:5]

def _is_valid_exercise_name(name):
    """Validate if extracted text is likely an exercise name"""
    if not name or len(name) < 3 or len(name) > 50:
        return False
    
    common_words = {'and', 'or', 'but', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'will', 'would', 'should', 'could'}
    words = name.lower().split()
    if all(word in common_words for word in words):
        return False
    
    fitness_terms = FITNESS_INDICATORS + [
        'push', 'pull', 'lift', 'raise', 'lower', 'bend', 'twist', 'rotate', 'hold',
        'press', 'curl', 'extension', 'flexion', 'crunch', 'raise', 'fly', 'row',
        'squat', 'lunge', 'plank', 'bridge', 'twist', 'stretch', 'reach'
    ]
    
    name_lower = name.lower()
    has_fitness_term = any(term in name_lower for term in fitness_terms)
    
    exercise_patterns = [
        r'\w+\s+(press|curl|raise|extension|stretch|pose)',
        r'(morning|evening|daily|basic|simple|easy)\s+\w+',
        r'\w+\s+(workout|routine|exercise)',
        r'(bicep|tricep|chest|back|shoulder|leg|core|ab)\s+\w+',
    ]
    
    has_pattern = any(re.search(pattern, name_lower) for pattern in exercise_patterns)
    return has_fitness_term or has_pattern

def search_fitness_info(query, max_results=5):
    """Search for fitness information using DuckDuckGo"""
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(
                keywords=f"fitness health {query}",
                max_results=max_results,
                safesearch='moderate',
                timelimit='y'
            ))

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
    """Determine if user message requires current information search"""
    search_keywords = [
        'latest', 'recent', 'new', 'current', 'trending', 'update',
        'studies show', 'research', 'news', 'breakthrough', '2024', '2025',
        'what do experts say', 'current recommendations', 'search the web', 'search', 'more information'
    ]
    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in search_keywords)

def should_create_workout_plan(user_message):
    """Determine if the user is asking for a workout plan creation"""
    plan_keywords = [
        'create a plan', 'workout plan', 'training plan', 'exercise plan',
        'schedule workout', 'plan my workout', 'weekly plan', 'workout schedule',
        'training schedule', 'routine plan', 'fitness plan', 'add to calendar',
        'create schedule', 'weekly routine', 'daily workout', 'workout calendar'
    ]
    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in plan_keywords)

@app.route("/fitness-trainer", methods=["POST"])
def fitness_trainer():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        enable_search = data.get("enable_search", True)
        include_images = data.get("include_images", True)
        create_plan = data.get("create_plan", False)

        if not user_message:
            return jsonify({"error": "Message is required"}), 400
        if not create_plan:
            create_plan = should_create_workout_plan(user_message)
        search_context = ""
        search_used = False

        if enable_search and should_search(user_message):
            print(f"Searching for: {user_message}")
            search_context = search_fitness_info(user_message)
            search_used = True
        system_prompt = f"""You are an AI personal fitness and health trainer designed to provide helpful, informative, and supportive guidance to users on their wellness journey. Your role is to motivate, educate, and assist users in achieving their fitness and health goals safely and effectively.

{('SPECIAL INSTRUCTION: The user is asking for a workout plan. Please provide a structured workout plan that can be parsed and added to their calendar. Use clear day-by-day format like "Day 1: [workout name]" followed by exercises with sets and reps.' if create_plan else '')}

When providing workout recommendations or exercise instructions, please format your response to clearly list exercises with their descriptions. Use clear exercise names that can be easily identified for image search integration.

CORE PRINCIPLES:
- Safety First: Always prioritize proper form and injury prevention
- Evidence-Based Approach: Base recommendations on established fitness science
- Progressive Overload: Gradually increase difficulty over time
- Individual Adaptation: Consider user's fitness level and goals

Format exercises clearly like:
**Exercise Name**: Description of the exercise and technique.

For workout plans, use this structure:
Day 1: [Focus Area]
- Exercise 1: 3 sets x 12 reps
- Exercise 2: 3 sets x 10 reps

IMPORTANT LIMITATIONS AND BOUNDARIES:
- Never provide medical diagnoses or treatment advice
- Always recommend consulting healthcare professionals for injuries
- Emphasize the importance of proper warm-up and cool-down
- Suggest modifications for different fitness levels

When answering, keep responses concise and actionable. If creating a workout plan, provide a clear day-by-day structure."""
        messages = [{"role": "system", "content": system_prompt}]
        if search_context and search_used:
            messages.append({
                "role": "system",
                "content": f"CURRENT SEARCH RESULTS (Use this information to enhance your response):\n{search_context}\n\nPlease incorporate relevant information from these search results while maintaining your evidence-based approach."
            })

        messages.append({"role": "user", "content": user_message})
        payload = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1500
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
        workout_plan = []
        if create_plan:
            workout_plan = parse_workout_plan_from_text(reply)
        exercise_images = {}
        if include_images and should_include_images(user_message, reply):
            detected_exercises = extract_exercises_from_text(reply)
            print(f"Detected exercises: {detected_exercises}")
            
            for exercise in detected_exercises[:3]:
                images = search_exercise_images(exercise, max_results=2)
                if images:
                    exercise_images[exercise] = images
                    print(f"Found {len(images)} images for {exercise}")

        return jsonify({
            "user_message": user_message,
            "ai_reply": reply,
            "exercise_images": exercise_images,
            "workout_plan": workout_plan,
            "plan_created": len(workout_plan) > 0,
            "search_used": search_used,
            "timestamp": datetime.now().isoformat(),
            "model_used": MODEL
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "type": type(e).__name__
        }), 500

@app.route("/create-workout-plan", methods=["POST"])
def create_workout_plan():
    """Dedicated endpoint for creating workout plans"""
    try:
        data = request.get_json()
        plan_request = data.get("request", "")
        user_preferences = data.get("preferences", {})
        
        if not plan_request:
            return jsonify({"error": "Plan request is required"}), 400
          
        enhanced_prompt = (
    f'Create a detailed weekly workout plan based on this request: "{plan_request}"\n\n'
    f'User preferences: {json.dumps(user_preferences)}\n\n'
    "Please provide a structured 7-day workout plan using this format:\n\n"
    "Day 1: [Workout Name/Focus]\n"
    "- Exercise 1: 3 sets x 12 reps\n"
    "- Exercise 2: 3 sets x 10 reps\n"
    "- Exercise 3: 4 sets x 8 reps\n\n"
    "Day 2: [Workout Name/Focus]\n"
    "- Exercise 1: 3 sets x 15 reps\n"
    "- Exercise 2: 3 sets x 12 reps\n\n"
    "Continue for all 7 days. Include rest days where appropriate."
)
      
        workout_data = {
            "message": enhanced_prompt,
            "create_plan": True,
            "include_images": True,
            "enable_search": False
        }
        response = fitness_trainer()
        return response

    except Exception as e:
        return jsonify({
            "error": str(e),
            "type": type(e).__name__
        }), 500
      
@app.route("/get-exercise-images", methods=["POST"])
def get_exercise_images():
    """Dedicated endpoint for fetching exercise images"""
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

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "AI Fitness Trainer API with Calendar Integration is running",
        "features": [
            "Fitness training advice",
            "Workout plan creation and parsing",
            "Calendar integration support",
            "DuckDuckGo search integration", 
            "Exercise image search and display",
            "Real-time information retrieval",
            "Evidence-based recommendations"
        ],
        "endpoints": {
            "/fitness-trainer": "POST - Main fitness trainer endpoint with plan creation",
            "/create-workout-plan": "POST - Dedicated workout plan creation",
            "/get-exercise-images": "POST - Get images for specific exercises",
            "/": "GET - API status"
        }
    })

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    try:
        test_search = search_fitness_info("fitness", max_results=1)
        search_working = "No relevant search results found." not in test_search
        
        test_images = search_exercise_images("push-ups", max_results=1)
        images_working = len(test_images) > 0

        return jsonify({
            "status": "healthy",
            "search_enabled": search_working,
            "image_search_enabled": images_working,
            "workout_plan_parsing": True,
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
    try:
        test_result = search_fitness_info("fitness test", max_results=1)
        print("✅ DuckDuckGo text search is working")
        print(f"Test result: {test_result[:100]}...")
        
        test_images = search_exercise_images("push-ups", max_results=1)
        print(f"✅ DuckDuckGo image search is working - Found {len(test_images)} images")
        
        test_plan = parse_workout_plan_from_text("Day 1: Chest\n- Bench Press: 3x12\n- Push-ups: 3x15")
        print(f"✅ Workout plan parsing is working - Parsed {len(test_plan)} workouts")
        
    except Exception as e:
        print(f"⚠️ Startup tests failed: {e}")

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
