import React from 'react'

// function AllReviews() {
//     return (
//         <div>
//             <h2>hi</h2>
//         </div>
//     )
// }

// export default AllReviews

import { useEffect, useState } from "react";

export default function ReviewList({ movieId }) {
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadReviews();
  }, [movieId]);

  const loadReviews = async () => {
    try {
      const response = await fetch(`/api/movies/${movieId}/reviews`);
      const data = await response.json();
      setReviews(data);
    } catch (error) {
      console.error("Error loading reviews:", error);
    }
    setLoading(false);
  };

  if (loading) return <p>Loading reviews...</p>;

  return (
    <div className="review-list">
      <h2>Reviews</h2>

      {reviews.length === 0 && <p>No reviews yet.</p>}

      {reviews.map((review) => (
        <div key={review.id} className="review-card">
          <p><strong>Rating:</strong> {review.rating} / 10</p>
          <p>{review.text}</p>
          <hr />
        </div>
      ))}
    </div>
  );
}

