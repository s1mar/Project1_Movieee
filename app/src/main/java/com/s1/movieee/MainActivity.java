package com.s1.movieee;

import android.app.ActionBar;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.AsyncTask;
import android.os.Bundle;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.GridView;
import android.widget.ImageView;
import android.widget.Spinner;

import com.squareup.picasso.Picasso;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;

public class MainActivity extends Activity {


     myAdapter movieAdapter;
     movieQuery mQry;
    ArrayList<String> resultsOverview = new ArrayList<String>();



    private String[] seperator(int i, String[] y) {
        String[] result = new String[y.length];
        int index = 0;

        switch (i) {                             //1. for image path
            case 1:
                for (String s : y) {
                    for (String v : s.split("'",2)) {
                        result[index] = "http://image.tmdb.org/t/p/w185/" + v;
                        break;
                    }

                    index+=1;

                }

                break;
            case 2:                             //2.for title
                for (String s : y) {
                    int c = 1;
                    for (String v : s.split("'", 3)) {
                        if(c==3){break;}
                        else {
                            result[index] = v;
                        }
                        c+=1;
                    }

                    index++;

                }
                break;

            case 3:                                         //3. for Vote
                for (String s : y) {
                    int c = 1;
                    for (String v : s.split("'", 3)) {
                        if(c==4){break;}
                        else {
                            result[index] = v;
                        }
                        c+=1;
                    }

                    index++;

                }
                break;

            default:
                for (String s : y) {
                    for (String v : s.split("'",2)) {
                        result[index] = "http://image.tmdb.org/t/p/w185/" + v;
                        break;
                    }

                    index+=1;

                }
                break;

        }
        return result;

    }





    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        movieAdapter = new myAdapter(this ,new String[0],resultsOverview);
        GridView gV = (GridView)findViewById(R.id.grid_view_mainGrid);
        gV.setAdapter(movieAdapter);

        gV.setOnItemClickListener(new AdapterView.OnItemClickListener() {
            @Override
            public void onItemClick(AdapterView<?> parent, View view, int position, long id) {


                String movie_name = movieAdapter.movieTitle[position];
                String movie_vote = movieAdapter.movieVote[position];
                String movie_link = movieAdapter.movieImageLink[position];
                Intent goto_Detail = new Intent(MainActivity.this, DetailActivity.class)
                                    .putExtra("MName",movie_name)
                                    .putExtra("MVote",movie_vote)
                                    .putExtra("MOver",movieAdapter.movieOverview.get(position))
                                    .putExtra("MImage",movie_link);


                startActivity(goto_Detail);
            }
        });

    }


    @Override
    protected void onStart() {
        super.onStart();

        mQry=new movieQuery();
        //Inflating and setting a spinner view in the action bar
        ActionBar x = getActionBar();
        View spinnerMenu = getLayoutInflater().inflate(R.layout.spinner_menu, null);
        x.setCustomView(spinnerMenu);
        x.setDisplayShowCustomEnabled(true);

        //Setting A listner on Spinner
        Spinner spin = (Spinner)spinnerMenu.findViewById(R.id.spin);
        spin.setSelection(0);
        spin.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {

                String choice = "";

                switch (position) {

                    case 1:
                        choice = "popular";
                        break;
                    case 2:
                        choice = "ratedR";
                        break;
                    case 3:
                        choice = "kidsPopular";
                        break;
                    case 4:
                        choice = "releaseOfTheYear";
                        break;
                    default:
                        choice = "popular";
                        break;

                }

                fetchMovieData x = new fetchMovieData();
                x.execute(mQry.movieQueryGenerator(choice));
                //Log.v("Inside Listner:choice", choice);
               // Log.v("Inside Listner", mQry.MovieQuery);
            }


            @Override
            public void onNothingSelected(AdapterView<?> parent) {

                //do nothing

            }
        });

    }

    public class fetchMovieData extends AsyncTask<URL, Void, String[]> {
        final String LOG_TAG = getClass().getSimpleName();

        protected String[] doInBackground(URL... params) {

            HttpURLConnection conn = null;
            BufferedReader reader = null;
            String fetchedDataMovies = null;



            try {
                conn = (HttpURLConnection) mQry.urlMovieQuery.openConnection();
                conn.setRequestMethod("GET");
                conn.connect();


                // Read the input stream into a String
                InputStream inputStream = conn.getInputStream();
                StringBuffer buffer = new StringBuffer();
                if (inputStream == null) {
                    // Nothing to do.
                    return null;
                }
                reader = new BufferedReader(new InputStreamReader(inputStream));

                String line;
                while ((line = reader.readLine()) != null) {
                    // Since it's JSON, adding a newline isn't necessary (it won't affect parsing)
                    // But it does make debugging a *lot* easier if you print out the completed
                    // buffer for debugging.
                    buffer.append(line + "\n");
                }

                if (buffer.length() == 0) {
                    // Stream was empty.  No point in parsing.
                    return null;
                }
                fetchedDataMovies = buffer.toString();
                //Log.v(LOG_TAG, "MOVIE JSON String :" + fetchedDataMovies);


            } catch (IOException e) {
                Log.e(LOG_TAG, "Error ", e);

                return null;
            } finally {
                if (conn != null) {
                    conn.disconnect();
                }
                if (reader != null) {
                    try {
                        reader.close();
                    } catch (final IOException e) {
                        Log.e(LOG_TAG, "Error closing stream", e);
                    }
                }
            }
            try {
                return getMovieDataFromJson(fetchedDataMovies);  // returns String Array
            } catch (JSONException e) {
                Log.e(LOG_TAG, e.getMessage(), e);
                e.printStackTrace();
            }
            return null;
        }






        protected String[] getMovieDataFromJson(String fetchedDataMovies) throws JSONException {

// These are the names of the JSON objects that need to be extracted.
            final String MD_RESULTS = "results";
            final String MD_IMAGE_POSTER = "poster_path";
            final String MD_RATING = "adult";
            final String MD_OVERVIEW = "overview";
            final String MD_RELEASE_DATE = "release_date";
            final String MD_IMAGE_BACKDROP = "backdrop_path";
            final String MD_VOTE = "vote_average";
            final String MD_TITLE = "title";

            JSONObject fetchedDataMoviesJson = new JSONObject(fetchedDataMovies);
            JSONArray movieArray = fetchedDataMoviesJson.getJSONArray(MD_RESULTS);

            ArrayList<String> resultStrs = new ArrayList<String>();
            resultsOverview.clear();

            for (int i = 0; i < movieArray.length(); i++) {

                // Get the JSON object representing the day
                JSONObject movieNumber = movieArray.getJSONObject(i);
                String movieImage = movieNumber.getString(MD_IMAGE_POSTER);
                String movieTitle = movieNumber.getString(MD_TITLE);
                String movieVote = movieNumber.getString(MD_VOTE);

                //for description
                String movieOverview = movieNumber.getString(MD_OVERVIEW);
                resultsOverview.add(i,movieOverview);


                String result = movieImage + "'" + movieTitle + "'" + movieVote;

               resultStrs.add(i, result);

            }
            String[] resultsArray = new String[movieArray.length()];

            int index = 0;
            for (String s : resultStrs) {
                resultsArray[index] = s;
                index += 1;
               // Log.v("getMfromJson", "Forecast entry: " + s);
            }

            return resultsArray;
        }


        @Override
        protected void onPostExecute(String[] strings) {
            super.onPostExecute(strings);

            if(strings!=null){

                movieAdapter.clear();
                movieAdapter.upd(strings);
                movieAdapter.notifyDataSetChanged();
            }

        }
    }


    public class myAdapter extends BaseAdapter{


        private final Context context;
        String[] movieImageLink;
        String[] movieTitle;
        String[] movieVote;
        ArrayList<String> movieOverview = new ArrayList<String>();


        // the context is needed to inflate views in getView()
        public myAdapter(Context context,String[] x,ArrayList<String> y)
        {
            this.context = context;
            movieImageLink = seperator(1, x);
            movieTitle = seperator(2,x);
            movieVote = seperator(3,x);
            movieOverview = y;
        }

        public void upd(String[]x){

            movieImageLink = seperator(1, x);
            movieTitle = seperator(2,x);
            movieVote = seperator(3,x);

        }

        @Override
        public int getCount() {
            return movieImageLink.length;
        }

        public void clear()
        {
            movieImageLink = new String[0];
            movieTitle = new String[0];


        }

        @Override
        public Object getItem(int position) {
            return null ;
        }
        @Override
        public long getItemId(int position) {
            return 0;
        }
        @Override
        public View getView(int position, View convertView, ViewGroup parent) {

            if (convertView == null) {
                convertView = LayoutInflater.from(context)
                        .inflate(R.layout.grid_element, parent, false);
            }


            ImageView movieImageView = (ImageView) convertView.findViewById(R.id.image_view_movieImage);
            Picasso.with(context).load(movieImageLink[position]).into(movieImageView);



            return convertView;
        }

            }


}

