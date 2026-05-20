import { useState } from 'react'
import './App.css'

function sendButton(String content, File file) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('text', content);

  fetch('/api/upload', {
    method: 'POST',
    body: formData
  });

  return (
    <button className="send" onClick={onSquareClick}>
      {value}
    </button>
  );
}

function App() {
  <div>
    <div> 
      (messages list, maps over messages array) 
    </div>
    <div> (input area at bottom)
        <button> (attach file) </button>
        <textarea>Add a message or file</textarea>
        <button> (send) </button>
    </div>
  </div>
}
