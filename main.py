import 'package:flutter/material.dart';
import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cached_network_image/cached_network_image.dart';

// Data class for exercise images
class ExerciseImage {
  final String url;
  final String title;
  final String source;
  final int width;
  final int height;
  final String type; // 'animated' or 'static'

  ExerciseImage({
    required this.url,
    required this.title,
    required this.source,
    required this.width,
    required this.height,
    required this.type,
  });

  factory ExerciseImage.fromJson(Map<String, dynamic> json) {
    return ExerciseImage(
      url: json['url'] ?? '',
      title: json['title'] ?? '',
      source: json['source'] ?? '',
      width: json['width'] ?? 0,
      height: json['height'] ?? 0,
      type: json['type'] ?? 'static',
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'url': url,
      'title': title,
      'source': source,
      'width': width,
      'height': height,
      'type': type,
    };
  }

  bool get isAnimated => type == 'animated';
}

// Enhanced chat message class with exercise images
class _ChatMessage {
  final String text;
  final bool isUser;
  final DateTime timestamp;
  final Map<String, List<ExerciseImage>> exerciseImages;

  _ChatMessage({
    required this.text,
    required this.isUser,
    DateTime? timestamp,
    this.exerciseImages = const {},
  }) : timestamp = timestamp ?? DateTime.now();

  Map<String, dynamic> toFirestore() {
    return {
      'text': text,
      'isUser': isUser,
      'timestamp': Timestamp.fromDate(timestamp),
      'exerciseImages': exerciseImages.map(
        (key, value) => MapEntry(
          key,
          value.map((img) => img.toJson()).toList(),
        ),
      ),
    };
  }

  factory _ChatMessage.fromFirestore(Map<String, dynamic> data) {
    Map<String, List<ExerciseImage>> images = {};
    
    if (data['exerciseImages'] != null) {
      final imagesData = data['exerciseImages'] as Map<String, dynamic>;
      images = imagesData.map((key, value) {
        final imageList = (value as List).map((img) => 
          ExerciseImage.fromJson(img as Map<String, dynamic>)
        ).toList();
        return MapEntry(key, imageList);
      });
    }

    return _ChatMessage(
      text: data['text'] ?? '',
      isUser: data['isUser'] ?? false,
      timestamp: (data['timestamp'] as Timestamp?)?.toDate() ?? DateTime.now(),
      exerciseImages: images,
    );
  }
}

class ConsultationPage extends StatefulWidget {
  const ConsultationPage({super.key});

  @override
  State<ConsultationPage> createState() => _ConsultationPageState();
}

class _ConsultationPageState extends State<ConsultationPage> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_ChatMessage> _messages = [];
  bool _isLoading = false;
  final FirebaseFirestore _firestore = FirebaseFirestore.instance;
  final FirebaseAuth _auth = FirebaseAuth.instance;

  @override
  void initState() {
    super.initState();
    _loadChatHistory();
  }

  // Load previous chat messages from Firestore
  Future<void> _loadChatHistory() async {
    try {
      final user = _auth.currentUser;
      if (user == null) return;

      final querySnapshot = await _firestore
          .collection('chats')
          .doc(user.uid)
          .collection('messages')
          .orderBy('timestamp', descending: false)
          .get();

      final loadedMessages = querySnapshot.docs.map((doc) {
        return _ChatMessage.fromFirestore(doc.data());
      }).toList();

      setState(() {
        _messages.addAll(loadedMessages);
      });

      _scrollToBottom();
    } catch (e) {
      print('Error loading chat history: $e');
    }
  }

  // Save a message to Firestore
  Future<void> _saveMessageToFirestore(_ChatMessage message) async {
    try {
      final user = _auth.currentUser;
      if (user == null) return;

      await _firestore
          .collection('chats')
          .doc(user.uid)
          .collection('messages')
          .add(message.toFirestore());
    } catch (e) {
      print('Error saving message: $e');
    }
  }

  @override
  Future<void> sendMessage(String prompt) async {
    // Trim whitespace and check if the prompt is actually meaningful
    final trimmedPrompt = prompt.trim();
    if (trimmedPrompt.isEmpty) {
      return; // Don't send empty or whitespace-only messages
    }

    final data = {
      "message": trimmedPrompt,
      "include_images": true, // Enable image search
    };

    try {
      final response = await http
          .post(
            Uri.parse("https://web-production-54d1f.up.railway.app/fitness-trainer"),
            headers: {"Content-Type": "application/json"},
            body: json.encode(data),
          )
          .timeout(const Duration(seconds: 60));

      if (response.statusCode == 200) {
        final responseData = json.decode(response.body);

        // Extract the AI reply from the response
        String responseText = "";
        Map<String, List<ExerciseImage>> exerciseImages = {};

        if (responseData is Map<String, dynamic>) {
          responseText = responseData["ai_reply"]?.toString() ?? "No AI response received";
          
          // Parse exercise images
          if (responseData["exercise_images"] != null) {
            final imagesData = responseData["exercise_images"] as Map<String, dynamic>;
            exerciseImages = imagesData.map((exerciseName, imageList) {
              final images = (imageList as List).map((img) =>
                ExerciseImage.fromJson(img as Map<String, dynamic>)
              ).toList();
              return MapEntry(exerciseName, images);
            });
          }
        } else {
          responseText = "Invalid response format";
        }

        final aiMessage = _ChatMessage(
          text: responseText,
          isUser: false,
          exerciseImages: exerciseImages,
        );

        setState(() {
          _isLoading = false;
          _messages.add(aiMessage);
        });

        // Save AI response to Firestore
        await _saveMessageToFirestore(aiMessage);

        _scrollToBottom();
      } else {
        final errorMessage = _ChatMessage(
          text: "Error: ${response.statusCode} ${response.reasonPhrase}",
          isUser: false,
        );

        setState(() {
          _isLoading = false;
          _messages.add(errorMessage);
        });

        await _saveMessageToFirestore(errorMessage);
        _scrollToBottom();
      }
    } catch (e) {
      final errorMessage = _ChatMessage(text: "Error: $e", isUser: false);

      setState(() {
        _isLoading = false;
        _messages.add(errorMessage);
      });

      await _saveMessageToFirestore(errorMessage);
      _scrollToBottom();
    }
  }

  void _scrollToBottom() {
    // Scrolls down to the latest message after a short delay
    // to allow the UI to build the new message.
    Timer(const Duration(milliseconds: 100), () {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _handleSend(String text) async {
    // Trim whitespace and check if there's actual content
    final trimmedText = text.trim();
    if (trimmedText.isEmpty) {
      return; // Don't send empty messages
    }

    // Prevent multiple simultaneous requests
    if (_isLoading) {
      return;
    }

    final userMessage = _ChatMessage(text: trimmedText, isUser: true);

    setState(() {
      _messages.add(userMessage);
      _controller.clear();
      _isLoading = true;
    });

    // Save user message to Firestore
    await _saveMessageToFirestore(userMessage);

    _scrollToBottom();

    // Send message to external AI service
    sendMessage(trimmedText);
  }

  void _showImageDialog(ExerciseImage image) {
    showDialog(
      context: context,
      builder: (BuildContext context) {
        return Dialog(
          backgroundColor: Colors.transparent,
          child: Container(
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surface,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ClipRRect(
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
                  child: CachedNetworkImage(
                    imageUrl: image.url,
                    fit: BoxFit.cover,
                    placeholder: (context, url) => const Center(
                      child: CircularProgressIndicator(),
                    ),
                    errorWidget: (context, url, error) => Container(
                      height: 200,
                      color: Colors.grey[300],
                      child: const Icon(Icons.error, size: 50),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    children: [
                      Text(
                        image.title,
                        style: Theme.of(context).textTheme.titleMedium,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Source: ${image.source}',
                        style: Theme.of(context).textTheme.bodySmall,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      TextButton(
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('Close'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: const Text(
          "AI Consultation",
          style: TextStyle(
            fontSize: 24,
            fontWeight: FontWeight.bold,
            fontFamily: 'CrimsonText',
          ),
        ),
        backgroundColor: Theme.of(context).colorScheme.primary,
        foregroundColor: Theme.of(context).colorScheme.onPrimary,
        elevation: 1,
      ),
      body: Column(
        children: [
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.all(16.0),
              itemCount: _messages.length,
              itemBuilder: (context, index) {
                final message = _messages[index];
                return _buildMessageBubble(message);
              },
            ),
          ),
          if (_isLoading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8.0),
              child: LinearProgressIndicator(),
            ),
          _buildTextComposer(),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(_ChatMessage message) {
    final bubbleAlignment = message.isUser
        ? CrossAxisAlignment.end
        : CrossAxisAlignment.start;
    final bubbleColor = message.isUser
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.secondaryContainer;
    final textColor = message.isUser
        ? Theme.of(context).colorScheme.onPrimary
        : Theme.of(context).colorScheme.onSecondaryContainer;

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 5.0),
      child: Column(
        crossAxisAlignment: bubbleAlignment,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: 14.0,
              vertical: 10.0,
            ),
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.75,
            ),
            decoration: BoxDecoration(
              color: bubbleColor,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  message.text,
                  style: TextStyle(fontFamily: 'CrimsonText', color: textColor),
                ),
                // Display exercise images if available
                if (message.exerciseImages.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  ...message.exerciseImages.entries.map((entry) =>
                    _buildExerciseImageSection(entry.key, entry.value, textColor)
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildExerciseImageSection(String exerciseName, List<ExerciseImage> images, Color textColor) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          exerciseName.toUpperCase(),
          style: TextStyle(
            fontWeight: FontWeight.bold,
            fontSize: 12,
            color: textColor.withOpacity(0.8),
            fontFamily: 'CrimsonText',
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          height: 120,
          child: ListView.builder(
            scrollDirection: Axis.horizontal,
            itemCount: images.length,
            itemBuilder: (context, index) {
              final image = images[index];
              return Container(
                margin: const EdgeInsets.only(right: 8),
                child: GestureDetector(
                  onTap: () => _showImageDialog(image),
                  child: Container(
                    width: 120,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                        color: image.isAnimated 
                            ? Colors.orange.withOpacity(0.6)  // Orange border for GIFs
                            : textColor.withOpacity(0.3),
                        width: image.isAnimated ? 2 : 1,
                      ),
                    ),
                    child: Stack(
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: CachedNetworkImage(
                            imageUrl: image.url,
                            fit: BoxFit.cover,
                            placeholder: (context, url) => Container(
                              color: Colors.grey[300],
                              child: Center(
                                child: Column(
                                  mainAxisAlignment: MainAxisAlignment.center,
                                  children: [
                                    SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        valueColor: AlwaysStoppedAnimation<Color>(
                                          image.isAnimated ? Colors.orange : Colors.grey,
                                        ),
                                      ),
                                    ),
                                    if (image.isAnimated) ...[
                                      const SizedBox(height: 4),
                                      Text(
                                        'GIF',
                                        style: TextStyle(
                                          fontSize: 10,
                                          color: Colors.orange[700],
                                          fontWeight: FontWeight.bold,
                                        ),
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                            ),
                            errorWidget: (context, url, error) => Container(
                              color: Colors.grey[300],
                              child: Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  Icon(
                                    image.isAnimated ? Icons.gif : Icons.fitness_center, 
                                    color: Colors.grey[600], 
                                    size: 24
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    exerciseName.split(' ').first,
                                    style: TextStyle(
                                      fontSize: 10,
                                      color: Colors.grey[600],
                                    ),
                                    textAlign: TextAlign.center,
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                        // GIF indicator badge
                        if (image.isAnimated)
                          Positioned(
                            top: 4,
                            right: 4,
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                              decoration: BoxDecoration(
                                color: Colors.orange,
                                borderRadius: BorderRadius.circular(8),
                                boxShadow: [
                                  BoxShadow(
                                    color: Colors.black.withOpacity(0.3),
                                    blurRadius: 2,
                                    offset: const Offset(0, 1),
                                  ),
                                ],
                              ),
                              child: const Text(
                                'GIF',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 8,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        const SizedBox(height: 8),
      ],
    );
  }

  Widget _buildTextComposer() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 8.0),
      decoration: BoxDecoration(
        color: Theme.of(context).cardColor,
        boxShadow: [
          BoxShadow(
            offset: const Offset(0, -1),
            blurRadius: 2.0,
            color: Colors.black.withOpacity(0.05),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _controller,
              onSubmitted: (value) {
                _handleSend(value);
              },
              decoration: const InputDecoration(
                hintText: "Ask me anything fitness!",
                border: InputBorder.none,
                contentPadding: EdgeInsets.all(8.0),
              ),
              style: const TextStyle(fontFamily: 'CrimsonText'),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.send),
            onPressed: () {
              _handleSend(_controller.text);
            },
            color: Theme.of(context).colorScheme.primary,
          ),
        ],
      ),
    );
  }
}
