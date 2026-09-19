const fs = require('fs');

const filePath = 'app/static/app.js';
let content = fs.readFileSync(filePath, 'utf8');

// Reemplazar los strings mal escapados
content = content.replace(
  /alert\('You\\'ve reached the rate limit\. Please wait a minute before trying again\.'\);/g,
  'alert("You\'ve reached the rate limit. Please wait a minute before trying again.");'
);

content = content.replace(
  /alert\("You\\'ve reached the rate limit\. Please wait a minute before trying again\."\);/g,
  'alert("You\'ve reached the rate limit. Please wait a minute before trying again.");'
);

fs.writeFileSync(filePath, content, 'utf8');
console.log('Fixed string literals');
