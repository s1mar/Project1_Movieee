package com.s1.movieee;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.widget.ImageView;
import android.widget.TextView;

import com.squareup.picasso.Picasso;

public class DetailActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_detail);
        Intent recieved = getIntent();

        String movie_name=recieved.getStringExtra("MName");
        String movie_votes = recieved.getStringExtra("MVote");
        String movie_overview = recieved.getStringExtra("MOver");
        String movie_link   =recieved.getStringExtra("MImage");

        TextView Mname = (TextView)findViewById(R.id.details_title);
        TextView Mvote = (TextView) findViewById(R.id.details_rating);
        TextView Mover = (TextView) findViewById(R.id.details_description);
        ImageView Mimage = (ImageView)findViewById(R.id.details_image_view);

        Picasso.with(this).load(movie_link).into(Mimage);
        Mover.setText(movie_overview);
        Mname.setText(movie_name);
        Mvote.setText(movie_votes);


    }
}
