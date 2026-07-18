/**
 * Streaming utilities for handling SSE responses from the RAG backend
 */

export interface StreamChunk {
  text: string;
  done: boolean;
  error?: string;
  citations?: Array<{
    index: number;
    document_name: string;
    section?: string;
    chunk_id: string;
  }>;
}

export interface StreamOptions {
  onChunk: (chunk: StreamChunk) => void;
  onError?: (error: Error) => void;
  onComplete?: (fullText: string, citations?: StreamChunk['citations']) => void;
}

/**
 * Parses a Server-Sent Events line into a StreamChunk
 */
export function parseSSELine(line: string): StreamChunk | null {
  if (!line.startsWith('data: ')) {
    return null;
  }
  
  const jsonStr = line.slice(6).trim();
  if (!jsonStr) {
    return null;
  }
  
  try {
    return JSON.parse(jsonStr) as StreamChunk;
  } catch (e) {
    console.error('Failed to parse SSE data:', jsonStr, e);
    return null;
  }
}

/**
 * Streams a chat response from the API
 * Uses Server-Sent Events (SSE) format
 */
export async function streamChat(
  endpoint: string,
  body: {
    query: string;
    session_id?: string;
    user_id?: string;
    filters?: Record<string, unknown>;
    system_prompt?: string;
  },
  headers: Record<string, string>,
  options: StreamOptions
): Promise<void> {
  const { onChunk, onError, onComplete } = options;
  
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      let errorMsg = response.statusText;
      try {
        const errorData = await response.json();
        errorMsg = errorData.detail || errorMsg;
      } catch {
        // Ignore parse errors
      }
      throw new Error(errorMsg);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';
    let lastCitations: StreamChunk['citations'] | undefined;

    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      
      // Process complete lines
      const lines = buffer.split('\n');
      buffer = lines.pop() || ''; // Keep incomplete line in buffer
      
      for (const line of lines) {
        const trimmedLine = line.trim();
        if (!trimmedLine) continue;
        
        const chunk = parseSSELine(trimmedLine);
        if (!chunk) continue;
        
        // Accumulate text
        if (chunk.text) {
          fullText += chunk.text;
        }
        
        // Store citations if present (they come with the final chunk)
        if (chunk.citations) {
          lastCitations = chunk.citations;
        }
        
        // Notify caller
        onChunk(chunk);
        
        // Check if stream is complete
        if (chunk.done) {
          onComplete?.(fullText, lastCitations);
          return;
        }
        
        // Handle errors
        if (chunk.error) {
          throw new Error(chunk.error);
        }
      }
    }
    
    // Process any remaining buffer
    if (buffer.trim()) {
      const chunk = parseSSELine(buffer.trim());
      if (chunk) {
        onChunk(chunk);
        if (chunk.done) {
          onComplete?.(fullText || chunk.text, chunk.citations || lastCitations);
        }
      }
    }
  } catch (error) {
    const err = error instanceof Error ? error : new Error(String(error));
    onError?.(err);
    throw err;
  }
}

/**
 * Hook-friendly streaming function that returns a promise resolving to the complete response
 */
export async function streamChatToCompletion(
  endpoint: string,
  body: {
    query: string;
    session_id?: string;
    user_id?: string;
    filters?: Record<string, unknown>;
    system_prompt?: string;
  },
  headers: Record<string, string>,
  onProgress?: (text: string) => void
): Promise<{ text: string; citations?: StreamChunk['citations'] }> {
  return new Promise((resolve, reject) => {
    let accumulatedText = '';
    let citations: StreamChunk['citations'] | undefined;
    
    streamChat(endpoint, body, headers, {
      onChunk: (chunk) => {
        if (chunk.text) {
          accumulatedText += chunk.text;
          onProgress?.(accumulatedText);
        }
        if (chunk.citations) {
          citations = chunk.citations;
        }
      },
      onComplete: (fullText, finalCitations) => {
        resolve({ 
          text: fullText, 
          citations: finalCitations || citations 
        });
      },
      onError: (error) => {
        reject(error);
      },
    }).catch(reject);
  });
}
